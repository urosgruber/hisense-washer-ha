# Hisense Washer

This app shows the status of a Hisense washer in Home Assistant. The washer
connects to this app instead of the ConnectLife cloud host
`wash-eu-link.hijuconn.com`. **The cloud is off by default**: the washer
talks only to this app, also when the internet is down.

The app only reads. It cannot start, stop or change a wash. The washer
encrypts its commands, and the app does not have the key.

## How the washer reaches the app

1. The DNS server answers `wash-eu-link.hijuconn.com` with the IP address
   of this Home Assistant host.
2. The washer always connects to port 443. Home Assistant itself uses 443,
   so the app listens on **4444**. To use another host port, change it in
   the app's Network panel.
3. A destination-NAT rule on the gateway changes the port from 443 to 4444
   for the washer's IP address only.
4. Set the option `washer_ip` to the washer's IP address. The app then
   refuses every other device on port 4444. Give the washer a fixed IP
   address (a DHCP reservation) first.

Port 4444 is open to your LAN. The app accepts a connection only after a
valid login from the washer it recorded at the first cloud login. With
`washer_ip` set, it also refuses every other address.

The washer accepts any TLS certificate. The app makes its own certificate
at the first start.

## The first login

With the cloud off, the app answers the washer's login with replies that it
recorded from the real cloud. So the app needs **one** cloud login first:

1. Open **Washer (admin)** in the sidebar. Only admins see it.
2. Click **Cloud on**. The app drops the washer, and the washer logs in
   again through the cloud within about a minute.
3. When the page shows "Login recorded: yes", click **Cloud off**.

## The cloud switch

Turn the cloud on only when you need the ConnectLife app, for example for a
program that starts only from that app. While the cloud is on, the app
forwards everything to ConnectLife, and Hisense sees the washer's data.

- The cloud turns off by itself after `cloud_max_hours` (default 2).
- A restart of the app always comes back with the cloud off.
- Only admins can turn it on. The dashboard card only shows it.

If the cloud cannot be reached, the app answers the washer itself, as with
the cloud off. The admin page then shows the error.

The app finds the real cloud through a public DNS server (option
`cloud_resolver`, default `1.1.1.1`), because your own DNS points the host
to this app. Set `cloud_address` to use a fixed IP address instead.

## Home Assistant

With MQTT on (the default), the app creates the **Hisense Washer** device:
phase, minutes left, end time, program, temperature, spin speed, the
options (Pre-wash, Steam, Cold wash, Extra rinse, Quicker, Anti crease), door lock, energy and water of the
running wash, totals, connection, cloud state, and the "Cycle" event.

The program names come from a Hisense 5S washer. Another model can use
other program codes; the Program entity is then unknown. The admin page
"Raw status bytes" helps to find the codes.

**Total energy** and **Total water** work in the Energy dashboard.

When the washer drops off the network for a short time, the entities keep
the last state for 10 minutes.

## Dashboard card

The app installs its own dashboard card at every start. You need no HACS.
After the first install and after each app update, reload the browser page
once (Cmd+Shift+R or Ctrl+Shift+R). Otherwise the dashboard says "Custom
element doesn't exist". In the Companion app, use Settings → Companion app
→ Debugging → Reset frontend cache, then open the app again.

```yaml
type: custom:hisense-washer-card
```

### History of energy and water

Home Assistant keeps long-term statistics of **Total energy** and **Total
water**. The built-in Statistics graph card shows them per day:

```yaml
type: vertical-stack
title: Washer – last 14 days
cards:
  - type: statistics-graph
    entities:
      - entity: sensor.hisense_washer_total_energy
        name: Energy
    stat_types: [change]
    chart_type: bar
    period: day
    days_to_show: 14
  - type: statistics-graph
    entities:
      - entity: sensor.hisense_washer_total_water
        name: Water
    stat_types: [change]
    chart_type: bar
    period: day
    days_to_show: 14
```

## Notifications

When a wash ends, the app sends a message to the phones in
`notify_targets`. Use the notify service names of the Companion app, for
example:

```yaml
notify_targets:
  - mobile_app_my_phone
  - mobile_app_other_phone
```

The list is empty by default: nobody gets a message until you add a phone.
If the washer drops off the network just before the end, the message says
"The wash has probably ended."

## Rollback

1. Remove the DNS override for `wash-eu-link.hijuconn.com`.
2. Remove the NAT rule.
3. Stop the app. The washer logs in to ConnectLife again within a few
   minutes. Switch the washer off and on if it does not.
