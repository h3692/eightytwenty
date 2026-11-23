---
name: eightytwenty
description: Start an eightytwenty deck for a case competition, pitch, assignment or project.
argument-hint: "[case prompt, brief or problem]"
disable-model-invocation: true
---

The user started eightytwenty with this brief:

$ARGUMENTS

If the brief is empty, ask the user for the case prompt or problem, and to attach any files that come with it, in one question, then wait for the reply. Otherwise the brief and any files the user attached are the case.

Then do what "using eightytwenty" does: call the eightytwenty `get_playbook` tool and follow its order.
