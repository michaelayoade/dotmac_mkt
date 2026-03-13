# Jinja2 + Alpine.js Template Patterns

## Alpine.js Attribute Quoting (CRITICAL)
Always use SINGLE quotes for `x-data` attributes with `tojson`:
```html
<!-- CORRECT -->
<div x-data='{ items: {{ items | tojson }} }'>

<!-- WRONG — breaks Alpine -->
<div x-data="{ items: {{ items | tojson }} }">
```

## Enum Display
Python `str, enum.Enum` renders as raw uppercase in Jinja2. Always apply filters:
```html
{{ status | replace('_', ' ') | title }}
```

## None Handling
`default('')` only works for UNDEFINED variables, not Python None:
```html
<!-- CORRECT for potentially None values -->
{{ var if var else '' }}

<!-- WRONG — None still renders as "None" -->
{{ var | default('') }}
```

## Dynamic Tailwind Classes
String interpolation like `bg-{{ color }}-50` gets purged by Tailwind. Use dict lookup:
```html
{% set color_map = {'success': 'bg-green-50', 'warning': 'bg-yellow-50'} %}
<div class="{{ color_map.get(status, 'bg-gray-50') }}">
```

## Dark Mode
All templates support dark mode via Tailwind's `dark:` prefix. Always provide dark variants:
```html
<div class="bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100">
```

## CSRF in Forms
Every `<form method="POST">` MUST include `{{ request.state.csrf_form | safe }}`.
