import os
from datetime import datetime, timezone


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)

from flask import Flask, flash, redirect, render_template, request, url_for
from flask_sqlalchemy import SQLAlchemy

from swd20weaponmod import (
    ONCE_PER_WEAPON,
    WEAPON_LIMITS,
    Mod,
    MOD_STAT_CHANGES,
    Weapon as RulesWeapon,
    _situational_bonus,
    plan_modification_take10,
    resolve_one_day,
)

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-secret-key")

_db_url = os.environ.get("DATABASE_URL", "sqlite:///weapons.db")
# For relative SQLite paths, ensure the parent directory exists
if _db_url.startswith("sqlite:///") and not _db_url.startswith("sqlite:////"):
    _rel = _db_url[len("sqlite:///"):]
    _dir = os.path.dirname(os.path.join(os.path.dirname(os.path.abspath(__file__)), _rel))
    if _dir:
        os.makedirs(_dir, exist_ok=True)
    _db_url = "sqlite:///" + os.path.join(os.path.dirname(os.path.abspath(__file__)), _rel)

app.config["SQLALCHEMY_DATABASE_URI"] = _db_url
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["TEMPLATES_AUTO_RELOAD"] = True
if _db_url.startswith("sqlite"):
    from sqlalchemy.pool import NullPool
    app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {"poolclass": NullPool}

db = SQLAlchemy(app)


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class DBWeapon(db.Model):
    __tablename__ = "weapon"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    weapon_type = db.Column(db.String(50), nullable=False)
    base_cost = db.Column(db.Integer, nullable=False)
    personalized = db.Column(db.Boolean, default=False)
    skill_modifier = db.Column(db.Integer, default=0, nullable=False, server_default="0")
    created_at = db.Column(db.DateTime, default=_utcnow)

    applied_mods = db.relationship(
        "DBAppliedMod", backref="weapon", lazy=True, order_by="DBAppliedMod.id",
        cascade="all, delete-orphan",
    )
    in_progress = db.relationship(
        "DBInProgressMod", backref="weapon", uselist=False, lazy=True,
        cascade="all, delete-orphan",
    )

    def to_rules_weapon(self) -> RulesWeapon:
        w = RulesWeapon(
            name=self.name,
            weapon_type=self.weapon_type,
            base_cost=self.base_cost,
            personalized=self.personalized,
        )
        w.applied_mods = [Mod(m.mod_name) for m in self.applied_mods]
        return w

    @property
    def max_mods(self) -> int:
        rules = WEAPON_LIMITS[self.weapon_type]
        return rules["personal"] if self.personalized else rules["custom"]

    @property
    def mod_count(self) -> int:
        return len(self.applied_mods)

    @property
    def slots_remaining(self) -> int:
        return self.max_mods - self.mod_count

    @property
    def modified_price(self) -> int:
        return int(self.base_cost * (1 + 0.5 * self.mod_count))


class DBAppliedMod(db.Model):
    __tablename__ = "applied_mod"
    id = db.Column(db.Integer, primary_key=True)
    weapon_id = db.Column(db.Integer, db.ForeignKey("weapon.id"), nullable=False)
    mod_name = db.Column(db.String(50), nullable=False)
    completed_at = db.Column(db.DateTime, default=_utcnow)


class DBInProgressMod(db.Model):
    __tablename__ = "in_progress_mod"
    id = db.Column(db.Integer, primary_key=True)
    weapon_id = db.Column(db.Integer, db.ForeignKey("weapon.id"), nullable=False)
    mod_name = db.Column(db.String(50), nullable=False)
    skill_modifier = db.Column(db.Integer, nullable=False)
    synergy_bonus = db.Column(db.Boolean, default=False)
    mastercraft_bonus = db.Column(db.Boolean, default=False)
    no_tools_penalty = db.Column(db.Boolean, default=False)
    target_price = db.Column(db.Integer, nullable=False)
    remaining_credits = db.Column(db.Integer, nullable=False)
    day_count = db.Column(db.Integer, default=0)
    dc = db.Column(db.Integer, nullable=False)
    started_at = db.Column(db.DateTime, default=_utcnow)


class DBRollHistory(db.Model):
    __tablename__ = "roll_history"
    id = db.Column(db.Integer, primary_key=True)
    weapon_id = db.Column(db.Integer, db.ForeignKey("weapon.id"), nullable=False)
    mod_name = db.Column(db.String(50), nullable=False)
    day_number = db.Column(db.Integer, nullable=True)   # None for final check
    d20_roll = db.Column(db.Integer, nullable=False)
    skill_modifier = db.Column(db.Integer, nullable=False)
    situational_bonus = db.Column(db.Integer, nullable=False)
    total_check = db.Column(db.Integer, nullable=False)
    dc = db.Column(db.Integer, nullable=False)
    met_dc = db.Column(db.Boolean, nullable=False)
    credits_earned = db.Column(db.Integer, default=0)
    remaining_after = db.Column(db.Integer, nullable=True)
    is_final = db.Column(db.Boolean, default=False)
    rolled_at = db.Column(db.DateTime, default=_utcnow)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    weapons = DBWeapon.query.order_by(DBWeapon.created_at.desc()).all()
    return render_template("index.html", weapons=weapons)


@app.route("/weapon/new", methods=["GET", "POST"])
def new_weapon():
    if request.method == "POST":
        weapon = DBWeapon(
            name=request.form["name"].strip(),
            weapon_type=request.form["weapon_type"],
            base_cost=int(request.form["base_cost"]),
            personalized=request.form.get("personalized") == "on",
        )
        db.session.add(weapon)
        db.session.commit()
        return redirect(url_for("weapon_detail", weapon_id=weapon.id))

    return render_template("new_weapon.html", weapon_types=WEAPON_LIMITS)


@app.route("/weapon/<int:weapon_id>")
def weapon_detail(weapon_id):
    weapon = db.get_or_404(DBWeapon, weapon_id)
    rules_weapon = weapon.to_rules_weapon()
    available_mods = [m for m in Mod if rules_weapon.can_apply(m)[0]]

    all_rolls = (DBRollHistory.query
                 .filter_by(weapon_id=weapon_id)
                 .order_by(DBRollHistory.rolled_at)
                 .all())
    roll_history: dict[str, list] = {}
    for r in all_rolls:
        roll_history.setdefault(r.mod_name, []).append(r)

    return render_template(
        "weapon_detail.html",
        weapon=weapon,
        available_mods=available_mods,
        mod_stat_changes=MOD_STAT_CHANGES,
        Mod=Mod,
        ONCE_PER_WEAPON=ONCE_PER_WEAPON,
        roll_history=roll_history,
    )


@app.route("/weapon/<int:weapon_id>/mod/new", methods=["GET", "POST"])
def start_mod(weapon_id):
    weapon = db.get_or_404(DBWeapon, weapon_id)

    if weapon.in_progress:
        flash("A modification is already in progress on this weapon.")
        return redirect(url_for("weapon_detail", weapon_id=weapon_id))
    if weapon.slots_remaining == 0:
        flash("No modification slots remaining.")
        return redirect(url_for("weapon_detail", weapon_id=weapon_id))

    if request.method == "POST":
        mod = Mod(request.form["mod"])
        skill_modifier = int(request.form["skill_modifier"])
        synergy_bonus = request.form.get("synergy_bonus") == "on"
        mastercraft_bonus = request.form.get("mastercraft_bonus") == "on"
        no_tools_penalty = request.form.get("no_tools_penalty") == "on"

        dc = WEAPON_LIMITS[weapon.weapon_type]["dc"]
        target_price = int(weapon.base_cost * (1 + 0.5 * (weapon.mod_count + 1)))
        ip = DBInProgressMod(
            weapon_id=weapon.id,
            mod_name=mod.value,
            skill_modifier=skill_modifier,
            synergy_bonus=synergy_bonus,
            mastercraft_bonus=mastercraft_bonus,
            no_tools_penalty=no_tools_penalty,
            target_price=target_price,
            remaining_credits=target_price,
            day_count=0,
            dc=dc,
        )
        db.session.add(ip)
        db.session.commit()
        flash("Modification started. Make a daily check each session — roll or take 10.")
        return redirect(url_for("weapon_detail", weapon_id=weapon_id))

    rules_weapon = weapon.to_rules_weapon()
    available_mods = [m for m in Mod if rules_weapon.can_apply(m)[0]]
    return render_template(
        "start_mod.html",
        weapon=weapon,
        available_mods=available_mods,
        mod_stat_changes=MOD_STAT_CHANGES,
        ONCE_PER_WEAPON=ONCE_PER_WEAPON,
    )



@app.route("/weapon/<int:weapon_id>/skill", methods=["POST"])
def update_weapon_skill(weapon_id):
    weapon = db.get_or_404(DBWeapon, weapon_id)
    new_modifier = int(request.form["skill_modifier"])
    old_modifier = weapon.skill_modifier
    weapon.skill_modifier = new_modifier
    if weapon.in_progress:
        weapon.in_progress.skill_modifier = new_modifier  # type: ignore[union-attr]
    db.session.commit()
    flash(f"Skill modifier updated from +{old_modifier} to +{new_modifier}.")
    return redirect(url_for("weapon_detail", weapon_id=weapon_id))



@app.route("/weapon/<int:weapon_id>/mod/roll", methods=["POST"])
def roll_day(weapon_id):
    weapon = db.get_or_404(DBWeapon, weapon_id)
    ip = weapon.in_progress
    if not ip:
        flash("No modification in progress.")
        return redirect(url_for("weapon_detail", weapon_id=weapon_id))

    d20 = int(request.form["d20_roll"])
    situational = _situational_bonus(ip.synergy_bonus, ip.mastercraft_bonus, ip.no_tools_penalty)
    met, check_result, progress = resolve_one_day(d20, ip.skill_modifier, ip.dc, situational)

    ip.day_count += 1
    credits_earned = 0
    if met:
        credits_earned = min(progress, ip.remaining_credits)
        ip.remaining_credits = max(0, ip.remaining_credits - progress)
        if ip.remaining_credits == 0:
            flash(f"Day {ip.day_count}: check {check_result}, progress {progress} cr — work complete! Make your final check.")
        else:
            flash(f"Day {ip.day_count}: check {check_result}, progress {progress} cr. Remaining: {ip.remaining_credits} cr.")
    else:
        flash(f"Day {ip.day_count}: check {check_result} failed DC {ip.dc}. No progress today.")

    db.session.add(DBRollHistory(
        weapon_id=weapon_id,
        mod_name=ip.mod_name,
        day_number=ip.day_count,
        d20_roll=d20,
        skill_modifier=ip.skill_modifier,
        situational_bonus=situational,
        total_check=check_result,
        dc=ip.dc,
        met_dc=met,
        credits_earned=credits_earned,
        remaining_after=ip.remaining_credits,
        is_final=False,
    ))
    db.session.commit()
    return redirect(url_for("weapon_detail", weapon_id=weapon_id))


@app.route("/weapon/<int:weapon_id>/mod/final", methods=["POST"])
def final_check(weapon_id):
    weapon = db.get_or_404(DBWeapon, weapon_id)
    ip = weapon.in_progress
    if not ip:
        flash("No modification in progress.")
        return redirect(url_for("weapon_detail", weapon_id=weapon_id))
    if ip.remaining_credits > 0:
        flash("Work is not yet complete — keep rolling daily progress.")
        return redirect(url_for("weapon_detail", weapon_id=weapon_id))

    d20 = int(request.form["d20_final"])
    situational = _situational_bonus(ip.synergy_bonus, ip.mastercraft_bonus, ip.no_tools_penalty)
    check_result = d20 + ip.skill_modifier + situational
    mod_name = ip.mod_name
    dc = ip.dc
    skill_modifier = ip.skill_modifier

    db.session.add(DBRollHistory(
        weapon_id=weapon_id,
        mod_name=mod_name,
        day_number=None,
        d20_roll=d20,
        skill_modifier=skill_modifier,
        situational_bonus=situational,
        total_check=check_result,
        dc=dc,
        met_dc=(check_result >= dc),
        credits_earned=0,
        remaining_after=None,
        is_final=True,
    ))
    db.session.delete(ip)
    if check_result >= dc:
        db.session.add(DBAppliedMod(weapon_id=weapon.id, mod_name=mod_name))
        db.session.commit()
        flash(f"Final check {check_result} vs DC {dc} — success! Modification complete.")
    elif check_result >= dc - 4:
        db.session.commit()
        flash(f"Final check {check_result} vs DC {dc} — failed. All time, money, and effort are wasted.")
    else:
        db.session.commit()
        flash(f"Final check {check_result} vs DC {dc} — failed by 5+. Weapon is DAMAGED and must be repaired before use!")

    return redirect(url_for("weapon_detail", weapon_id=weapon_id))


@app.route("/weapon/<int:weapon_id>/mod/abandon", methods=["POST"])
def abandon_mod(weapon_id):
    weapon = db.get_or_404(DBWeapon, weapon_id)
    if weapon.in_progress:
        db.session.delete(weapon.in_progress)
        db.session.commit()
        flash("Modification abandoned.")
    return redirect(url_for("weapon_detail", weapon_id=weapon_id))


@app.route("/weapon/<int:weapon_id>/delete", methods=["POST"])
def delete_weapon(weapon_id):
    weapon = db.get_or_404(DBWeapon, weapon_id)
    name = weapon.name
    db.session.delete(weapon)
    db.session.commit()
    flash(f'"{name}" deleted.')
    return redirect(url_for("index"))


with app.app_context():
    db.create_all()


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0")
