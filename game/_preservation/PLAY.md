# Playing KOF ALLSTAR offline (by hand)

Everything runs on this PC: a small local server answers the game instead of Netmarble's servers. The game files
are already patched and the tables built, so playing takes two steps: start the server, then start the game.
Commands are typed in PowerShell or Command Prompt.

## 1. Start the server

```
cd F:\Games\Mobile\Android\kofg\_preservation
python server\kofserver.py
```

It prints `KOF ALLSTAR local server on http://127.0.0.1:18080 ...`. Leave that window open while you play. It
listens on this PC only (127.0.0.1, ports 18080 and 18081).

## 2. Start the game

In a second window:

```
cd F:\Games\Mobile\Android\kofg\_preservation
powershell -NoProfile -File tools\relaunch.ps1
```

This starts `KOF ALLSTAR.exe` in a 1280×720 window without the administrator prompt (the exe asks for admin only
for its anti-cheat, which the patch replaced) and closes a copy that is already running. The game's own log goes to
`server\logs\player.log`.

Then: update checks → title. If it asks you to sign in, keep the email already filled in and type any password.
Click the title screen. On the day's first sign-in the CHECK-IN LOG opens first. A mouse click is a tap; in
battle the AUTO button plays for you.

## 3. Stop

Close the game window first, then press Ctrl+C in the server window (or close it). The server saves your progress
as you play, in `server\state\save.json`.

## Accounts

Your own account is the one in place now: made on 2026-10-25 at your first offline sign-in, with the whole fighter
roster and no story progress yet. Every account also gets 5 Dungeon Keys and, once, 30 AUTO-CLEAR TICKETs and 12
tickets for each roulette.

To try a later point of the game without touching your own account, switch to a saved test account (game closed):

```
python tools\account.py                         (list the saved accounts)
python tools\account.py use test-20261026-exp   (switch to a test account)
python tools\account.py home                    (back to your own account)
```

`use` first saves the account in place (nothing you played is lost) and remembers your own one, so `home` brings it
back.

**Unlimited resources for testing.** Every saved test account is a test player: AP 999, 99,999,999 gold, 999,999
rubies, the other currencies at 999,999 and 999 of every item, topped up again after anything you spend. Their
fighters are also at the max level of their star grade (30 / 40 / 50 / 60 for 3★-6★, shown from the next sign-in), so
a test team clears dungeon runs on AUTO. To switch it for the account in place (game closed), including your own:

```
python tools\account.py unlimited on
python tools\account.py unlimited off
```

Test accounts worth trying:

| Name | Where it stands |
|---|---|
| `test-20261026-exp` | chapters 1-3 cleared, chapter 4 open, EXP dungeon EASY cleared (the roulettes were tested on it) |
| `test-20261026-chk` | the same point; the CHECK-IN LOG opens at every sign-in (day 1) |
| `test-20261026-ch1done` | chapter 1 done, chapter 2 open |

To start over as a brand-new player (nickname → starter → the 2023 start), close the game and run
`python tools\new_game.py`. It moves your account into `server\state\backup\` and prints its name;
`python tools\account.py use <that name>` brings it back. The new account is a test player with unlimited
resources; `python tools\new_game.py --normal` makes a regular one instead.

## What to try (the 2023 video 5 content)

- **Roulettes**: the two icons at the lobby's top right, EXCITING ROULETTE (no timer) and Fighter Growth Support
  Roulette ("N Day(s)").
  - START spins once for one ticket (OWNED / REQUIRED at the bottom). The prize lands in one of the three BINGO
    slots; with all three filled, Receive one before the next spin.
  - Receive sends that prize to the Mailbox (envelope icon at the top of the lobby). Three alike pay the BONUS 200%.
  - View Rate lists every prize's chance; the "[DAILY] Play Exciting Roulette" mission (Missions) counts spins.
  - Not there yet: the picture title over the wheel, the FREE (video ad) spins, and opening the prize boxes /
    using the awaken capsules.
- The CHECK-IN LOG (first sign-in of the day; rewards arrive by mail).
- DUNGEON → POWER UP DUNGEON → Kyokugenryu Dojo EXP Dungeon (EASY to EXPERT, AUTO-CLEAR, AUTO BATTLE).
- POWER UP DUNGEON → **Jackpot Gold Dungeon** (EASY, EXPERT): break Daruma dolls for gold until the timer ends.
  Breaking dolls fills the cat gauge; a full gauge starts **FEVER TIME** (special moves without cooldown for 10 s)
  and brings Lucky Cats to smash (1, then 2, then 3). EXPERT can be played 3 times a day (the row shows the runs
  left, e.g. 2/3).
- POWER UP DUNGEON → **Fighter Evolution Dungeon**: five element tabs (purple, blue, red, green, yellow), EASY to
  EXPERT each; a run pays that element's Evolution Material. At the boss, break the two Yata statues: the left (blue)
  one fills your power gauge, the right (red) one weakens the boss. **Evolving a 5★ fighter to 6★ now takes 30 of its
  element's material** plus gold (FIGHTER → a fighter → EVOLVE); lower grades still cost gold only.
- Story chapters 1-4 EP.1, SELECT SUPPORTER, Missions (DAILY / ACHIEVEMENT), the Mailbox.

Changed on 2026-10-28 to match the real game (PLAN.md "Real-game reference: community guides"; these apply to your
account too): fighter stats, CP and COST now follow the 2023 videos, so CP numbers are much smaller than before
(a Lv 2 Kyo '97 reads CP 735); the fighter EXP curve is flatter at the start, so fighters you levelled earlier show
higher levels for the same EXP; AP comes back 1 point every 2 minutes; the wrong element deals half damage; five
story teams from the start; friendship points stop at 10,000 and AUTO BATTLE repeats pay none; plus capsules go to
+99 per stat; limit break also takes KOF / All-Star, colour and rainbow souls; the Gold Dungeon's EXPERT can be
cleared 3 times a day.

`PLAN.md` lists what each feature does and what is still missing.

## If something goes wrong

- The game freezes on its first screens (it happens now and then right after startup): run `relaunch.ps1` again.
- Connection errors in the game: the server window isn't running; start it, then the game.
- Logs: `server\logs\requests-<date-time>.log` (every request the game made), `server\logs\player.log` (the game).
- After changing a table generator (`tools\gen_*.py`), rebuild as in PLAN.md "How to run" and restart the game;
  after changing `server\*.py`, restart the server.
