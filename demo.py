# demo.py — practical end-to-end test of Jarvis Phase 1-4
# Runs real API calls to prove everything works together.

import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from orchestrator import ai_classify_task, process_for_vscode

SEP = "-" * 60

def test(label, fn):
    print(f"\n{SEP}")
    print(f"  {label}")
    print(SEP)
    result = fn()
    print(result)

# ── 1. AI Classification
print(f"\n{'='*60}")
print("  JARVIS PRACTICAL DEMO")
print(f"{'='*60}")

print(f"\n{SEP}")
print("  TEST 1 -- AI Complexity Classification")
print(SEP)

cases = [
    "what is the difference between Promise and async/await?",
    "explain CSS flexbox",
    "build a complete Angular login page with JWT authentication",
    "create a full .NET API with authentication, database, and tests",
]
for task in cases:
    r = ai_classify_task(task)
    tag = "COMPLEX → terminal" if r["is_complex"] else "SIMPLE  → direct"
    print(f"  [{tag}]  {task[:65]}")

# ── 2. Simple question ───────────────────────────────────────
test(
    "TEST 2 — Simple question (no file context)",
    lambda: process_for_vscode(
        "What is the difference between ngOnInit and the constructor in Angular?"
    )
)

# ── 3. Question with file context ────────────────────────────
fake_component = """\
import { Component, OnInit } from '@angular/core';

@Component({
  selector: 'app-login',
  standalone: true,
  template: `
    <form (ngSubmit)="onSubmit()">
      <input [(ngModel)]="email" placeholder="Email">
      <input [(ngModel)]="password" type="password" placeholder="Password">
      <button type="submit">Login</button>
    </form>
  `
})
export class LoginComponent implements OnInit {
  email = '';
  password = '';

  ngOnInit() {}

  onSubmit() {
    console.log(this.email, this.password);
  }
}
"""

test(
    "TEST 3 — Question WITH active file context",
    lambda: process_for_vscode(
        "What's missing or wrong in this component? Give me 3 specific improvements.",
        file_path="src/app/login/login.component.ts",
        file_content=fake_component
    )
)

# ── 4. Selected code context ─────────────────────────────────
selection = """\
onSubmit() {
  console.log(this.email, this.password);
}
"""

test(
    "TEST 4 — Question with SELECTED code (selection beats full file)",
    lambda: process_for_vscode(
        "Improve this method — add proper HTTP call and error handling",
        file_path="login.component.ts",
        file_content=fake_component,
        selection=selection
    )
)

# ── 5. Complex task redirect ─────────────────────────────────
test(
    "TEST 5 — Complex task (should redirect to terminal)",
    lambda: process_for_vscode(
        "Build a complete Angular 18 login page with JWT, guards, and .NET API"
    )
)

print(f"\n{'='*60}")
print("  ALL TESTS COMPLETE")
print(f"{'='*60}\n")
