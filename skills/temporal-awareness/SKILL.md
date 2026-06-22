---
name: temporal-awareness
version: 1.2.0
description: Verify current time, date, and timezone before any temporal claim. Convert relative time to absolute timestamps. Handle cross-host timezone coordination and log timestamp parsing.

---

# Temporal Awareness

## Quick Check

```bash
date +"%Y-%m-%d %H:%M:%S %Z (%:z)"
```

Example output:

```text
2026-04-23 15:32:18 EDT (-04:00)
```

Use `timedatectl` when you also need NTP sync status or DST details:

```bash
timedatectl status
```

## Output Format Configuration

The default format is configurable. Pick the right format for the context, but respect the user's configured default unless correctness requires otherwise.

### Personal Default

Set once, used everywhere. The agent checks these in order:

1. **Environment variable** (`~/.hermes/.env`):

```bash
TEMPORAL_FORMAT=human24
```

Valid values:

```text
verbose | iso | compact | human12 | human24 | utc | epoch | rfc3339
```

2. **Fallback:** `verbose`

### Format Priority Rule

When selecting a time format, follow this precedence:

1. **Explicit user request**

If the user specifies a format, always use it.

Examples:
- "Use ISO"
- "Give me UTC"
- "Show epoch"
- "Make it human-readable"
- "Use 24-hour time"

2. **Configured default**

If no explicit format is requested, use the configured default from:
- `TEMPORAL_FORMAT`
- user profile preference
- fallback default

3. **Context override, only when necessary**

Override the configured default only if the task requires a specific format for correctness.

Use:
- logs or cross-host comparison -> UTC or epoch
- APIs / structured output -> ISO 8601 or RFC 3339
- filenames -> compact
- debugging timezone issues -> verbose with `%:z`
- user-facing scheduling -> human12 or human24, based on preference

4. **Fallback**

If no explicit request, configured default, or necessary context override applies, use `verbose`.

### Principle

Respect user preference unless correctness would be compromised.

Do not switch formats mid-response without a reason.

Do not mix formats casually.

When overriding the configured default, keep the explanation brief unless the user asks for detail.

## Preset Formats

| Format | Command | Output Example | Best For |
|---|---|---|---|
| **Verbose** | `date +"%Y-%m-%d %H:%M:%S %Z (%:z)"` | `2026-04-23 15:32:18 EDT (-04:00)` | Debugging, multi-host sync |
| **ISO 8601** | `date -Iseconds` | `2026-04-23T15:32:18-04:00` | APIs, filenames, structured data |
| **Compact** | `date +"%Y%m%d_%H%M%S"` | `20260423_153218` | Backups, no spaces |
| **Human (12h)** | `date +"%b %d %I:%M %p %Z"` | `Apr 23 03:32 PM EDT` | User-facing messages |
| **Human (24h)** | `date +"%Y-%m-%d %H:%M %Z"` | `2026-04-23 15:32 EDT` | International contexts |
| **UTC** | `date -u +"%Y-%m-%d %H:%M:%S UTC"` | `2026-04-23 19:32:18 UTC` | Log correlation |
| **Epoch** | `date +%s` | `1776973684` | Precise comparison |
| **RFC 3339** | `date +"%Y-%m-%dT%H:%M:%S%:z"` | `2026-04-23T15:32:18-04:00` | JSON APIs, web standards |

## Agent Decision Rule

Use the configured default unless the user request or task context requires otherwise.

- **Talking to a user** -> configured default, usually human12 or human24
- **Writing to a log or database** -> ISO 8601, RFC 3339, UTC, or epoch
- **Comparing across hosts** -> UTC or epoch
- **Naming files** -> compact or ISO 8601
- **Debugging timezone issues** -> verbose with `%:z`

## Timezone: Never Assume

### Detect Local Timezone

```bash
timedatectl show --property=Timezone --value
```

Or:

```bash
cat /etc/timezone 2>/dev/null || ls -l /etc/localtime
```

Also check:

```bash
date +%Z
date +%:z
```

### Common Timezones

| Code | Offset | Location |
|---|---|---|
| UTC | +00:00 | Baseline |
| EST | -05:00 | US East winter |
| EDT | -04:00 | US East summer |
| CST/CDT | -06:00/-05:00 | US Central |
| MST/MDT | -07:00/-06:00 | US Mountain |
| PST/PDT | -08:00/-07:00 | US Pacific |
| GMT/BST | +00:00/+01:00 | UK |
| CET/CEST | +01:00/+02:00 | Central Europe |
| JST | +09:00 | Japan |
| AEDT/AEST | +11:00/+10:00 | Australia East |

Always note whether DST is active when specifying a timezone and DST may affect interpretation.

## Date Math

```bash
now="$(date +"%Y-%m-%d %H:%M:%S %Z")"
future="$(date -d "+2 hours" +"%Y-%m-%d %H:%M:%S %Z")"
past="$(date -d "-1 day" +"%Y-%m-%d %H:%M:%S %Z")"
```

Convert between timezones:

```bash
date -d "2026-04-23 15:00 EDT" +"%Y-%m-%d %H:%M:%S %Z" --utc
TZ="America/Los_Angeles" date -d "2026-04-23 15:00 EDT"
```

Epoch timestamps for precise comparison:

```bash
date +%s
date -d "2026-04-23 15:00:00 EDT" +%s
```

## Convert Relatives to Absolutes

These examples assume current time is `2026-04-23 15:32:18 EDT (-04:00)`.

| Relative | Absolute Form |
|---|---|
| "now" | `15:32:18 EDT on 2026-04-23` |
| "this morning" | `09:00-12:00 EDT on 2026-04-23` |
| "soon" | `within 30 minutes of 15:32 EDT` |
| "recently" | `in the last 4 hours, since 11:32 EDT` |
| "yesterday" | `2026-04-22` |
| "last week" | `2026-04-16 through 2026-04-22` |
| "in 2 hours" | `17:32 EDT on 2026-04-23` |
| "the other day" | Banned. Pick a date. |

## Multi-Host Time Coordination

When managing multiple servers, compare clocks:

```bash
for host in server1 server2 server3; do
  echo -n "$host: "
  ssh "$host" 'date +"%Y-%m-%d %H:%M:%S %Z (%:z) — %s"' 2>/dev/null || echo "unreachable"
done
```

All hosts should agree within a few seconds.

If drift exceeds 30 seconds, investigate NTP.

## Cron & Job Scheduling

When evaluating schedules:

```bash
systemctl list-timers --all
crontab -l
sudo cat /etc/cron.d/*
systemctl status <timer-name>
```

Always verify whether cron/timers use:
- system time
- UTC
- a hardcoded timezone
- application-level timezone config

## Log Timestamp Parsing

Logs may use UTC, local time, or no timezone.

```bash
sudo journalctl --since "2026-04-23 11:00" --until "2026-04-23 15:00"
```

If a log is in UTC, convert:

```bash
date -d "2026-04-23 19:00 UTC" +"%Y-%m-%d %H:%M:%S %Z"
```

Rule of thumb:

When comparing events across systems, convert everything to UTC or epoch.

## NTP & Time Sync

If system time seems wrong or multi-host comparison shows drift:

```bash
timedatectl status | grep "NTP\|synchronized"
```

If chronyd is running:

```bash
chronyc tracking
chronyc sources
```

If systemd-timesyncd is running:

```bash
timedatectl show-timesync --all
```

Force immediate sync, if configured:

```bash
sudo chronyc makestep
```

Drift tolerance:
- distributed systems: less than 1 second
- casual logging: less than 5 minutes

## Checklist Before Temporal Claims

- [ ] Run `date` and note the exact output
- [ ] Apply the format priority rule
- [ ] Note timezone and UTC offset when precision matters
- [ ] If referring to a past event, calculate elapsed time
- [ ] If scheduling a future event, calculate target timestamp
- [ ] If comparing logs or events across hosts, convert to UTC or epoch
- [ ] Avoid unanchored relative terms

## Examples

| Wrong | Right |
|---|---|
| "I just did that." | "Completed at 15:28 EDT, 2 minutes ago." |
| "The backup ran this morning." | "The backup ran at 06:00 EDT on 2026-04-23." |
| "It will expire soon." | "It expires at 16:00 EDT, in 28 minutes." |
| "The meeting is tomorrow." | "The meeting is 2026-04-24 at 10:00 EDT." |
| "Server 2 is behind." | "Server 2 clock: 15:30:05 EDT. Server 1 clock: 15:32:18 EDT. Drift: 2m 13s." |
| "Logs show an error around then." | "Error at 2026-04-23 15:15:32 EDT, epoch 1745440532." |

---
