# Changelog

## 0.2.0

New fields, decoded from a session at the washer (Hisense 5S series).

- New entities: Program, Temperature, Steam, Extra rinse, Quicker (off, 1,
  2) and Rinses. "Door locked" is now on by default.
- The card shows the program, temperature and spin speed, the options that
  are on, a lock icon while the door is locked, and the connection.
- Delay start: the card shows when the wash ends and the time left.
- Fix: the time left is a 16-bit value. Before, a delay start of more than
  about 4 hours showed a wrong time.
- Fix: a ready washer with a program that starts with pre-wash or spin
  showed the phase "unknown". It now shows "idle".

## 0.1.2

- The admin page has a new page, "Raw status bytes". It shows the last
  40 different statuses and marks the bytes that changed. Use it to find
  the program, the door and the temperature in the status. The page
  reloads every 3 seconds.

## 0.1.1

Fixes from a code review, and hardening.

- The washer port accepts only the washer: a connection counts after a
  valid login with the washer id recorded at the cloud login. The new
  option `washer_ip` also refuses every other address.
- The admin page accepts requests only through Home Assistant (ingress).
- The cloud time limit keeps working when a drop of the washer fails.
- Cloud on, but the cloud is unreachable: the app answers the washer
  itself, and the admin page shows the error.
- A refused cloud login no longer overwrites the recorded login.
- "Cloud on" refuses 0, negative and invalid hours.
- A crash while a wash ends no longer counts the wash twice.
- The `device_port` option is gone. Change the host port in the Network
  panel.

## 0.1.0

First version.

- The washer logs in to this app. The ConnectLife cloud is off by default.
- An admin can turn the cloud on for a limited time on the admin page.
- Home Assistant entities: phase, minutes left, end time, spin speed,
  energy and water of the wash, totals for the Energy dashboard, and a
  "done" event.
- A dashboard card shows when the wash ends.
- A phone notification when the wash is done, to the phones you choose.
