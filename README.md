# Hisense washer: local control for Home Assistant

A local server for a Hisense washer (ConnectLife device protocol). The washer
logs in to this server instead of the ConnectLife cloud. Home Assistant gets
the washer's phase, time left, end time, energy and water over MQTT, and a
dashboard card.

The cloud is off by default. An admin can turn it on for a limited time.

Status: work in progress.

## Test

```bash
python3 -m unittest discover -s tests -v
```
