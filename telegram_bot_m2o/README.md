# Telegram Bot for Odoo

Manage Telegram bots from Odoo with configurable commands, inline keyboards, CRM lead creation, and an optional **smart AI fallback** via n8n (or any HTTP endpoint).

## Features

- Multiple bots per Odoo instance (each with its own token, commands, and webhook secret).
- Configurable commands with text / image / document / inline-keyboard responses, HTML formatting, and `{first_name}`-style placeholders.
- Phone collection via Telegram contact-share button.
- Automatic `res.partner` and `crm.lead` creation; full message history posted to the partner's chatter.
- **Fallback Webhook URL** for unmatched messages — wire any external workflow (n8n, Zapier, Make, custom API).

## Smart AI Fallback (n8n)

Set the `Fallback Webhook URL` field on the bot to forward unmatched messages to an external workflow. The module sends a JSON payload that an LLM-driven flow can act on directly.

### Forwarded payload

```json
{
  "bot_id": 1,
  "bot_name": "Many2one",
  "bot_username": "ndev_online_bot",
  "chat_id": "549709518",
  "user_id": "549709518",
  "user_name": "svyatoslavnadozirny",
  "first_name": "Svyatoslav",
  "last_name": false,
  "phone": "+380...",
  "partner_id": 42,
  "message_text": "Хочу замовити впровадження для 30 людей",
  "raw_message": { "...full Telegram update..." }
}
```

### Recommended n8n workflow

```
Webhook (POST)
  → AI Agent (Claude / GPT, structured output: user_reply, needs_human, category, summary, urgency)
  → Telegram: Reply to user      (chat_id = body.chat_id, text = output.user_reply)
  → IF needs_human == true
       → Telegram: Notify internal group  (with output.summary and full contact info)
```

The webhook node should respond with `{"ok": true}` (n8n's `Respond Immediately` mode is ideal — Telegram retries on slow responses).

### Why structure the LLM output

Asking the model for a JSON object (`user_reply`, `needs_human`, `category`, `summary`, `urgency`) lets you:

- Always reply to the user (good UX).
- Conditionally escalate only business-critical conversations.
- Forward a clean, LLM-rephrased summary to the team instead of the raw chat — saves the operator's reading time.

### Suggested team-notification template (HTML)

```
🚨 <b>Потрібна реакція менеджера</b>

📋 <b>Категорія:</b> {{ output.category }}
⚡ <b>Терміновість:</b> {{ output.urgency }}

📝 <b>Запит:</b>
{{ output.summary }}

👤 <b>Контакт:</b>
• Імʼя: {{ body.first_name }} {{ body.last_name }}
• Username: @{{ body.user_name }}
• Телефон: {{ body.phone }}
• Telegram: <a href="tg://user?id={{ body.user_id }}">відкрити чат</a>

💬 <b>Оригінал:</b>
<code>{{ body.message_text }}</code>
```

## Setup

1. Create a bot with `@BotFather` and copy the token.
2. In Odoo, open *Telegram* → *Bots* → *New*. Paste the token, set company / sales team / default salesperson, and save.
3. Click **Validate Token**, then **Start Bot** (this registers the webhook with Telegram and uploads the command list).
4. Optional: paste your fallback workflow URL into **Fallback Webhook URL**.
5. To pick up group messages, disable **Group Privacy** for the bot in `@BotFather` (`/mybots → Bot Settings → Group Privacy → Turn off`) or make the bot a group admin — Telegram bots only see commands / @mentions in groups by default.

## Requirements

- Odoo 19.0
- HTTPS-enabled Odoo (Telegram refuses non-HTTPS webhooks)
- `python3-requests`

## License

LGPL-3
