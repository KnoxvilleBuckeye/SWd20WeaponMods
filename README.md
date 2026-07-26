# SWd20 Weapon Modification Tracker

> **Fan Project Disclaimer:** This is an unofficial fan tool. *Star Wars* is the property of Disney/Lucasfilm Ltd. The *Star Wars Roleplaying Game* is published by Wizards of the Coast under license from Lucasfilm. This project is not affiliated with or endorsed by Disney, Lucasfilm, or Wizards of the Coast. No commercial use is intended or made.

A tool for calculating and tracking weapon modifications from the *Star Wars Roleplaying Game* (d20 system). Implements the full modification rules including daily progress rolls, skill bonuses, and in-progress state persistence across sessions.

## Running with Docker

```zsh
docker compose up --build
```

Open `http://localhost:8080` in your browser. The SQLite database is saved to `./data/weapons.db` and persists across container restarts.

`app.py`, `swd20weaponmod.py`, and `templates/` are volume-mounted, so changes to those files take effect immediately without rebuilding the image. Only `requirements.txt` or `Dockerfile` changes require `docker compose up --build`.

## Running without Docker

```zsh
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
flask run
```

Open `http://localhost:5000`.

There is also a CLI version:

```zsh
python3 swd20weaponmod.py
```

## How It Works

### Customized vs. Personalized

- **Customized** — modifications benefit any user who picks up the weapon
- **Personalized** — modifications only apply to the original owner; other users see base stats. If any modification is a personalization, all are.

### Modification Limits

| Weapon Type    | Max Customized | Max Personalized | Skill DC |
|----------------|:--------------:|:----------------:|:--------:|
| Blaster pistol | 2              | 3                | 15       |
| Blaster rifle  | 1              | 2                | 15       |
| Heavy weapons  | 1              | —                | 20       |
| Vibro weapons  | 1              | 2                | 10       |
| Slugthrowers   | 1              | 2                | 10       |
| Simple         | 0              | 1                | 5        |
| Exotic         | 0              | 1 (GM approval)  | 20       |

### Available Modifications

| Modification          | Effect                                      | Limit         |
|-----------------------|---------------------------------------------|---------------|
| Range increment       | +50% of base range (round down to even)     | Repeatable    |
| Damage +1             | +1 damage, −1 attack                        | Repeatable    |
| Threat range          | Threat range expanded by 1                  | Once per weapon |
| Reduce weight         | Weight reduced by half                      | Once per weapon |
| Accuracy +1           | +1 attack, −1 damage                        | Repeatable    |
| Multifire penalty     | Multifire penalty lessened by 1             | Once per weapon |
| Rapid Shot penalty    | Rapid Shot penalty lessened by 1            | Once per weapon |
| Fortitude save DC     | Fort save DC +2                             | Repeatable    |
| Durability            | Hardness +2, wound points +2                | Repeatable    |

### Cost Formula

Each modification increases the weapon's price by 50% of its base cost:

```
Modified price = base cost × (1 + 0.5 × number of modifications)
Materials cost = base cost ÷ 4  (per modification)
```

### Daily Progress

Each day, make a skill check (Repair or appropriate Craft) against the weapon's DC:

- **Success:** progress = check result × skill modifier
- **Failure:** no progress that day
- Work is complete when accumulated progress ≥ modified price

Each day's check is tracked individually. On the weapon detail page you can either enter your d20 roll or click **Take 10** — the choice is made per day, not locked in at the start. Taking 20 is not allowed.

Every roll is logged to a roll history table (d20, modifier, situational bonus, total check, DC, result, credits earned, remaining). The history is visible on the weapon detail page while the mod is in progress and remains accessible via the expandable history on each completed mod.

### Situational Modifiers

| Condition                                          | Modifier |
|----------------------------------------------------|:--------:|
| 5+ ranks in both Repair and relevant Craft (synergy) | +2     |
| Tech specialist with mastercraft ability assisting | +2       |
| Missing proper tools                               | −5       |

### Final Check

When daily work is complete, make one final skill check at the same DC:

- **Success** — modification complete
- **Failure** — all time, money, and effort lost
- **Failure by 5+** — weapon damaged; must be repaired before use

### Skill Modifier

The weapon detail page has a **Skill Modifier** field (left column) that stores the character's Repair / Craft modifier for that weapon. It pre-populates when starting a new modification and persists between mods.

If a character levels up mid-modification, update the modifier there — it takes effect on the next daily roll and does not affect accumulated progress.

## Project Structure

```
swd20weaponmod.py   — rules engine and CLI interface
app.py              — Flask web application and database models
templates/          — Jinja2 HTML templates
data/               — SQLite database (created at runtime)
Dockerfile
docker-compose.yml
requirements.txt
```

## Rules Reference

- *Star Wars Roleplaying Game Revised Core Rulebook*
- *Hero's Guide*
- *Arms and Equipment Guide*, Chapter 1 — Customizing and Personalizing Weapons

## Legal

This project uses mechanics derived from the d20 System, which is Open Game Content under the Open Game License v1.0a. See [LICENSE.TXT](LICENSE.TXT) for the full license text and Section 15 copyright notices.

*Star Wars*, blaster, vibroblade, and all related names and settings are trademarks of Disney/Lucasfilm Ltd. and are used here without permission for non-commercial fan purposes only.
