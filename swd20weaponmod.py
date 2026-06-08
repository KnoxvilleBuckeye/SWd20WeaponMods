import math
from dataclasses import dataclass, field
from enum import Enum


WEAPON_LIMITS = {
    "blaster pistol": {"custom": 2, "personal": 3, "dc": 15},
    "blaster rifle": {"custom": 1, "personal": 2, "dc": 15},
    "heavy weapons": {"custom": 1, "personal": 0, "dc": 20},
    "vibro weapons": {"custom": 1, "personal": 2, "dc": 10},
    "slugthrowers": {"custom": 1, "personal": 2, "dc": 10},
    "simple": {"custom": 0, "personal": 1, "dc": 5},
    "simple grenades": {"custom": 0, "personal": 0, "dc": None},
    "exotic": {"custom": 0, "personal": 1, "dc": 20},
}


class Mod(Enum):
    RANGE_INCREMENT = "range_increment"       # repeatable
    DAMAGE_PLUS_1 = "damage_plus_1"          # repeatable; -1 attack
    THREAT_RANGE = "threat_range"            # once per weapon
    REDUCE_WEIGHT = "reduce_weight"          # once per weapon
    ACCURACY_PLUS_1 = "accuracy_plus_1"      # repeatable; -1 damage
    MULTIFIRE_PENALTY = "multifire_penalty"  # once per weapon
    RAPID_SHOT_PENALTY = "rapid_shot_penalty" # once per weapon
    FORT_SAVE_DC = "fort_save_dc"            # repeatable
    DURABILITY = "durability"                # repeatable


ONCE_PER_WEAPON = {
    Mod.THREAT_RANGE,
    Mod.REDUCE_WEIGHT,
    Mod.MULTIFIRE_PENALTY,
    Mod.RAPID_SHOT_PENALTY,
}

MOD_STAT_CHANGES = {
    Mod.RANGE_INCREMENT: "Range increment +50% of base (round down to nearest even number)",
    Mod.DAMAGE_PLUS_1: "+1 damage, -1 attack",
    Mod.THREAT_RANGE: "Threat range expanded by 1",
    Mod.REDUCE_WEIGHT: "Weight reduced by half",
    Mod.ACCURACY_PLUS_1: "+1 attack, -1 damage",
    Mod.MULTIFIRE_PENALTY: "Multifire penalty lessened by 1",
    Mod.RAPID_SHOT_PENALTY: "Rapid Shot penalty lessened by 1",
    Mod.FORT_SAVE_DC: "Fortitude save DC +2",
    Mod.DURABILITY: "Hardness +2, wound points +2",
}


@dataclass
class Weapon:
    name: str
    weapon_type: str
    base_cost: int
    personalized: bool = False
    applied_mods: list[Mod] = field(default_factory=list)

    @property
    def _rules(self) -> dict:
        return WEAPON_LIMITS[self.weapon_type.lower()]

    @property
    def dc(self) -> int | None:
        return self._rules["dc"]

    @property
    def max_mods(self) -> int:
        return self._rules["personal"] if self.personalized else self._rules["custom"]

    @property
    def mod_count(self) -> int:
        return len(self.applied_mods)

    @property
    def modified_price(self) -> int:
        return int(self.base_cost * (1 + 0.5 * self.mod_count))

    @property
    def slots_remaining(self) -> int:
        return self.max_mods - self.mod_count

    def can_apply(self, mod: Mod) -> tuple[bool, str]:
        if self.dc is None:
            return False, "This weapon type cannot be modified."
        if self.mod_count >= self.max_mods:
            mode = "personalized" if self.personalized else "customized"
            return False, f"Modification limit reached ({self.max_mods} {mode} mods)."
        if mod in ONCE_PER_WEAPON and mod in self.applied_mods:
            return False, f"{mod.value} can only be applied once per weapon."
        return True, "OK"


@dataclass
class ModificationResult:
    success: bool
    reason: str = ""
    weapon_name: str = ""
    mod: Mod | None = None
    material_cost: int = 0
    modified_price: int = 0
    dc: int = 0
    check_result: int = 0
    daily_progress: int = 0
    days_required: int = 0
    stat_change: str = ""

    def __str__(self) -> str:
        if not self.success:
            return f"Cannot apply modification: {self.reason}"
        lines = [
            f"Weapon: {self.weapon_name}",
            f"Modification: {self.mod.value if self.mod else ''}",
            f"  Stat change: {self.stat_change}",
            f"  Modified price: {self.modified_price} credits",
            f"  Materials cost: {self.material_cost} credits (1/4 base price)",
            f"  Skill DC: {self.dc}",
            f"  Check result: {self.check_result}",
            f"  Daily progress: {self.daily_progress} credits/day",
            f"  Days required: {self.days_required}",
            f"  Final check required: DC {self.dc}",
        ]
        return "\n".join(lines)


def _situational_bonus(synergy_bonus: bool, mastercraft_bonus: bool, no_tools_penalty: bool) -> int:
    total = 0
    if synergy_bonus:
        total += 2
    if mastercraft_bonus:
        total += 2
    if no_tools_penalty:
        total -= 5
    return total


def plan_modification_take10(
    weapon: Weapon,
    mod: Mod,
    skill_modifier: int,
    synergy_bonus: bool = False,
    mastercraft_bonus: bool = False,
    no_tools_penalty: bool = False,
) -> ModificationResult:
    """Plan a modification using take-10. Returns total days and cost upfront."""
    can, reason = weapon.can_apply(mod)
    if not can:
        return ModificationResult(success=False, reason=reason)
    if skill_modifier <= 0:
        return ModificationResult(success=False, reason="Skill modifier must be positive to make daily progress.")

    dc = weapon.dc
    assert dc is not None

    situational = _situational_bonus(synergy_bonus, mastercraft_bonus, no_tools_penalty)
    check_result = 10 + skill_modifier + situational

    if check_result < dc:
        return ModificationResult(
            success=False,
            reason=f"Take-10 result {check_result} does not meet DC {dc}.",
        )

    next_modified_price = int(weapon.base_cost * (1 + 0.5 * (weapon.mod_count + 1)))
    material_cost = weapon.base_cost // 4
    daily_progress = check_result * skill_modifier
    days_required = math.ceil(next_modified_price / daily_progress)

    return ModificationResult(
        success=True,
        weapon_name=weapon.name,
        mod=mod,
        material_cost=material_cost,
        modified_price=next_modified_price,
        dc=dc,
        check_result=check_result,
        daily_progress=daily_progress,
        days_required=days_required,
        stat_change=MOD_STAT_CHANGES[mod],
    )


def resolve_one_day(
    d20_roll: int,
    skill_modifier: int,
    dc: int,
    situational: int = 0,
) -> tuple[bool, int, int]:
    """
    Resolve a single day's progress check.
    Returns (met_dc, check_result, progress).
    progress is 0 if DC not met.
    """
    check_result = d20_roll + skill_modifier + situational
    if check_result < dc:
        return False, check_result, 0
    progress = check_result * skill_modifier
    return True, check_result, progress


def apply_modification(weapon: Weapon, mod: Mod) -> None:
    """Record that a modification has been successfully applied."""
    can, reason = weapon.can_apply(mod)
    if not can:
        raise ValueError(reason)
    weapon.applied_mods.append(mod)


def weapon_summary(weapon: Weapon) -> str:
    mode = "Personalized" if weapon.personalized else "Customized"
    lines = [
        f"=== {weapon.name} ({weapon.weapon_type}) ===",
        f"  Base cost: {weapon.base_cost} credits",
        f"  Mode: {mode}",
        f"  Mods applied: {weapon.mod_count} / {weapon.max_mods}",
        f"  Current modified price: {weapon.modified_price} credits",
    ]
    if weapon.applied_mods:
        lines.append("  Applied modifications:")
        for m in weapon.applied_mods:
            lines.append(f"    - {m.value}: {MOD_STAT_CHANGES[m]}")
    return "\n".join(lines)


def prompt_int(prompt: str) -> int:
    while True:
        try:
            return int(input(prompt).strip())
        except ValueError:
            print("  Please enter a whole number.")


def prompt_yes_no(prompt: str) -> bool:
    while True:
        answer = input(prompt + " (y/n): ").strip().lower()
        if answer in ("y", "yes"):
            return True
        if answer in ("n", "no"):
            return False
        print("  Please enter y or n.")


def prompt_weapon_type() -> str:
    types = list(WEAPON_LIMITS.keys())
    print("\nWeapon types:")
    for i, t in enumerate(types, 1):
        limits = WEAPON_LIMITS[t]
        dc_str = str(limits["dc"]) if limits["dc"] else "—"
        print(f"  {i}. {t.title():<20} DC {dc_str:<4}  custom {limits['custom']}  personal {limits['personal']}")
    while True:
        choice = input("Choose weapon type (number or name): ").strip().lower()
        if choice.isdigit() and 1 <= int(choice) <= len(types):
            return types[int(choice) - 1]
        if choice in types:
            return choice
        print("  Invalid choice.")


def prompt_mod(weapon: Weapon) -> Mod:
    mods = list(Mod)
    print("\nAvailable modifications:")
    for i, m in enumerate(mods, 1):
        already_applied = m in weapon.applied_mods
        once_note = " [once-only — already applied]" if (m in ONCE_PER_WEAPON and already_applied) else \
                    " [once-only]" if m in ONCE_PER_WEAPON else ""
        print(f"  {i}. {m.value:<25} {MOD_STAT_CHANGES[m]}{once_note}")
    while True:
        choice = input("Choose modification (number): ").strip()
        if choice.isdigit() and 1 <= int(choice) <= len(mods):
            return mods[int(choice) - 1]
        print("  Invalid choice.")


def run_interactive() -> None:
    print("=== SWd20 Weapon Modification Calculator ===")

    name = input("\nWeapon name: ").strip() or "My Weapon"
    weapon_type = prompt_weapon_type()
    base_cost = prompt_int("Base cost (credits): ")
    personalized = prompt_yes_no("Personalized (for one user only)?")

    weapon = Weapon(name=name, weapon_type=weapon_type, base_cost=base_cost, personalized=personalized)
    print(f"\n{weapon_summary(weapon)}")

    while True:
        if weapon.slots_remaining == 0:
            print("\nNo modification slots remaining.")
            break

        print(f"\n{weapon.slots_remaining} slot(s) remaining.")
        if not prompt_yes_no("Add a modification?"):
            break

        mod = prompt_mod(weapon)
        skill_modifier = prompt_int("Skill modifier (ranks + INT + misc): ")
        take_10 = prompt_yes_no("Take 10?")
        synergy_bonus = prompt_yes_no("Synergy bonus (+2, 5+ ranks in both Repair and Craft)?")
        mastercraft_bonus = prompt_yes_no("Mastercraft bonus (+2, tech specialist assisting)?")
        no_tools_penalty = prompt_yes_no("Missing proper tools (-5)?")

        if take_10:
            result = plan_modification_take10(
                weapon=weapon,
                mod=mod,
                skill_modifier=skill_modifier,
                synergy_bonus=synergy_bonus,
                mastercraft_bonus=mastercraft_bonus,
                no_tools_penalty=no_tools_penalty,
            )
            print(f"\n{result}")
            mod_complete = result.success

        else:
            # Rolling: resolve each day separately until work is done
            can, reason = weapon.can_apply(mod)
            if not can:
                print(f"\nCannot apply modification: {reason}")
                mod_complete = False
            elif skill_modifier <= 0:
                print("\nSkill modifier must be positive to make daily progress.")
                mod_complete = False
            else:
                dc = weapon.dc
                assert dc is not None
                situational = _situational_bonus(synergy_bonus, mastercraft_bonus, no_tools_penalty)
                next_modified_price = int(weapon.base_cost * (1 + 0.5 * (weapon.mod_count + 1)))
                material_cost = weapon.base_cost // 4

                print(f"\n  Modification: {mod.value}  |  {MOD_STAT_CHANGES[mod]}")
                print(f"  Modified price: {next_modified_price} credits")
                print(f"  Materials cost: {material_cost} credits")
                print(f"  Skill DC: {dc}")
                print(f"  Roll a d20 each day and enter the result. Progress accumulates until done.")

                remaining = next_modified_price
                day = 1
                mod_complete = False

                while remaining > 0:
                    print(f"\n  --- Day {day} (remaining: {remaining} credits) ---")
                    d20 = prompt_int("  d20 roll: ")
                    met, check_result, progress = resolve_one_day(d20, skill_modifier, dc, situational)

                    if not met:
                        print(f"  Check result {check_result} — failed DC {dc}. No progress today.")
                    else:
                        remaining -= progress
                        print(f"  Check result {check_result} → {progress} credits progress. Remaining: {max(remaining, 0)}")

                    day += 1

                print(f"\n  Work complete after {day - 1} day(s). Make your final DC {dc} check.")
                final_roll = prompt_int("  Final check d20 roll: ")
                final_result = final_roll + skill_modifier + situational
                print(f"  Final check result: {final_result}")

                if final_result >= dc:
                    print("  Success! Modification complete.")
                    mod_complete = True
                elif final_result >= dc - 4:
                    print("  Failed. All time, money, and effort are wasted.")
                    mod_complete = False
                else:
                    print("  Failed by 5 or more — weapon is DAMAGED and must be repaired before use.")
                    mod_complete = False

        if mod_complete:
            if prompt_yes_no("\nRecord this modification on the weapon?"):
                apply_modification(weapon, mod)
                print(f"\n{weapon_summary(weapon)}")

    print(f"\nFinal weapon state:\n{weapon_summary(weapon)}")


if __name__ == "__main__":
    run_interactive()
