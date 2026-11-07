# Changelog

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
