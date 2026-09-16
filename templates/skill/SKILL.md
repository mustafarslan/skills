---
name: my-skill-name
description: Replace with what the skill does and when Claude should use it (e.g. "Use when the user asks to ...").
---

# My Skill Name

Copy this directory to `skills/<your-skill-name>/`, set `name` in the
frontmatter to match the directory name, and replace this body with your
instructions.

## When to use

Describe the situations or requests that should trigger this skill. Claude
decides whether to load the skill based on the `description` field in the
frontmatter, so put the key trigger phrases there too.

## Instructions

1. Step-by-step guidance Claude should follow.
2. Keep it concrete: commands to run, files to read, output format to produce.
3. Move long reference material into separate files (e.g. `references/guide.md`)
   next to this one and link to them, so they are only read when needed.

## Examples

Show a short example input and the expected result.
