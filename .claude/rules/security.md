# Security & Error Handling

## Never Use Bare `except:`
```python
# WRONG
try:
    num = Decimal(value)
except:
    continue

# CORRECT
try:
    num = Decimal(value)
except (ValueError, TypeError, ArithmeticError) as e:
    logger.warning("Invalid number: %s", e)
    continue
```

## Template Output Escaping
Jinja2 auto-escapes by default. `| safe` is only allowed for:
- `{{ request.state.csrf_form | safe }}` — CSRF input
- `{{ data | tojson | safe }}` — JSON for JavaScript

For user content: `{{ content | sanitize_html }}`
For newlines: `{{ comment.text | nl2br }}`

## CSRF Protection
Every `<form method="POST">` MUST include:
```html
{{ request.state.csrf_form | safe }}
```

## Log Levels
- `logger.debug()` — diagnostic details
- `logger.info()` — business events
- `logger.warning()` — unexpected but recoverable
- `logger.error()` — errors needing attention
- `logger.exception()` — exceptions with stack trace (inside `except`)
- **NEVER** log passwords, tokens, PII

## External Integrations
1. Config with empty string defaults (never production URLs)
2. `is_configured()` method
3. Raise clear error if unconfigured
