KOF ALLSTAR Offline - full package (personal copy, do not share)
=================================================================

This package holds the whole game: the PC client, its downloaded game data, the local offline server and your
saved progress. It is your own copy for moving to another PC. The game files belong to Netmarble / SNK, so please
don't upload or share this zip.

Install
-------
1. Extract the zip to a folder with about 12 GB free, e.g.  C:\Games\KOFAS
   (use Windows "Extract All" or 7-Zip; avoid Program Files).
2. Open the folder and double-click  play.cmd  to play. It starts the local server in its own window, then opens
   the game in a 1280x720 window. Keep the server window open while you play; close it to stop the server.
   The first time on a PC it also restores the game's settings (graphics, sign-in email).
   Nothing needs to be installed; nothing goes online.

If Windows shows "Windows protected your PC" for play.cmd: click "More info" -> "Run anyway".

Playing
-------
Sign in: if the game asks, keep the email already filled in and type any password.
A mouse click is a tap. In battle the AUTO button plays for you.
More in game\_preservation\PLAY.md (account switching, test accounts, new game).
For account tools, open a Command Prompt in this folder and use the bundled Python, e.g.:
    python\python.exe game\_preservation\tools\account.py

Your progress
-------------
Saved as you play in  game\_preservation\server\state\save.json  (other accounts in state\backup).
Copy the state folder to back it up.

Moving or removing
------------------
The folder can be moved anywhere; play.cmd works from wherever it is.
To remove the game, delete the folder.

Problems
--------
- The server window shows an error, or the game cannot connect: read the message in the server window
  (another program using port 18080 is the usual cause).
- The game's own log: game\_preservation\server\logs\player.log
