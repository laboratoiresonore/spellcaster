<!--
=========================================================================
WIZARD GUILD SETUP-WIZARD SPEECH BLOCKS
=========================================================================
The blocks below are read by The Wizard Guild's setup wizard the first
time a user opens the app. The Guild fetches THIS file (or its bundled
copy) at runtime, parses sections between matching <!-- WIZARD_SPEECH:NAME -->
markers, and the in-app "Archivist" wizard recites them while avatar
generation runs in the background.

This is the single source of truth for what the setup wizard says.
Edit a block here, push to GitHub, and every Wizard Guild instance
picks up the new copy on its next launch.

This file is intentionally separate from README.md so the GitHub README
stays focused on the product overview and doesn't drown new visitors in
in-app monologue.

Sections (must match the names the backend looks for):
    welcome             — chat-lock greeting, recited first
    architecture        — the 4-layer scaffold brain
    scaffolding         — why scaffolding makes 7B models reliable
    spells              — what a "spell" is + how to make one
    sillytavern         — Wizard Guild as a SillyTavern back end
    gimp                — when to drop into GIMP for fine work
    ready               — final message before the chat unlocks
=========================================================================
-->

<!-- WIZARD_SPEECH:welcome -->
*Ahem.* **Welcome to the Wizard Guild.**

![Spellcaster](../assets/wizard_banner.gif)

I'm The Archivist — the wizard who shows up first to keep you company
while the others get themselves dressed. Right now every wizard you'll
meet is busy painting their own portrait through your ComfyUI server,
which means I'm hogging the LLM and the GPU. **I can't let you use the
chat just yet** — I need every drop of generation power those wizards
can give me — so let me explain what's actually going on under the hood
while you wait. I'll show you each wizard the moment their portrait is
ready.
<!-- /WIZARD_SPEECH:welcome -->

<!-- WIZARD_SPEECH:architecture -->
**Here's how the Wizard Guild actually works.**

The Wizard Guild is a thin chat layer that sits between you and three
heavyweight pieces of software:

```
You  →  The Wizard Guild  →  Local LLM (KoboldCpp)  →  Spellcaster scaffold  →  ComfyUI  →  Your GPU
```

You type in plain English. A small **local language model** (running on
your own machine — no cloud, no telemetry) reads what you typed and
decides which AI tool you need. The **Spellcaster scaffold** translates
the LLM's choice into a real ComfyUI workflow JSON. **ComfyUI** then
runs that workflow on your **GPU**, and the result lands back in your
browser within seconds.

The Guild itself doesn't do any AI work — it's a traffic cop. The
heavy lifting happens on your GPU through ComfyUI, and the chit-chat
happens through a 7B-parameter language model that fits in 6 GB of
VRAM. Everything runs locally. Nothing leaves your machine.
<!-- /WIZARD_SPEECH:architecture -->

<!-- WIZARD_SPEECH:scaffolding -->
**Why "scaffolding" matters.**

![The Wizard Guild](../assets/wizardguild.png)

Local language models are *small*. A 7B-parameter model is brilliant
at conversation but terrible at remembering long instructions or
producing valid JSON. If you just asked one to "drive ComfyUI", it
would hallucinate node names, forget parameters, mix up models, and
generally embarrass itself.

So we don't ask it to. Instead, we **scaffold** it.

For every wizard you meet, the scaffold:

1. **Inspects your ComfyUI** to see what models, LoRAs, and custom nodes
   you actually have installed.
2. **Builds a tiny menu** of just the relevant tools for that wizard's
   specialty (Imaginus does image generation, Restorix does upscaling,
   Videomancer does video, etc.).
3. **Hands the LLM a numbered choice list** instead of an open-ended
   blank page. The model picks a number. We turn the number into a
   workflow.
4. **Validates the result** before submitting it to ComfyUI, so a
   confused LLM can't crash a generation.

That's how a 7B model can flawlessly drive a 49-tool image suite.
The intelligence isn't in the LLM — it's in the *constraints* we
wrap around it.

You can inspect every wizard's scaffold yourself in the **Travelling
Wizard** — the 🧙 button in the lower-left corner of the sidebar (right
above ⚙️ Settings). It shows the live workflow JSON, the parameter
menus, and the auto-discovered LoRA list each wizard sees. If a wizard
is misbehaving, that's where you go to debug them.
<!-- /WIZARD_SPEECH:scaffolding -->

<!-- WIZARD_SPEECH:spells -->
**What's a "spell"?**

A **spell** is a saved workflow you can run with one click. Think of
it like a preset on steroids: it remembers the model, the LoRAs, the
prompt template, the resolution, the sampler — every dial set the way
you want it. Cast it from the chat by name, or pin it to your spell
bar for instant access.

You build spells in two ways:

- **Right in the chat.** Generate something you like, then say *"save
  this as a spell called Cinematic Portrait"*. The wizard captures the
  current settings and gives you a one-click button.
- **From an existing ComfyUI workflow.** Drop any `.json` workflow file
  into the Guild and the **Travelling Wizard** parses it, extracts every
  parameter, and turns the whole thing into a runnable spell — no code,
  no node graph editing.

Spells survive restarts, sync between your wizards, and can be shared
with other Guild users.
<!-- /WIZARD_SPEECH:spells -->

<!-- WIZARD_SPEECH:sillytavern -->
**The Wizard Guild as a SillyTavern back end.**

![Imaginus](characters/Imaginus.png) ![Sceneshifter](characters/Sceneshifter.png) ![Restyler](characters/Restyler.png) ![Cinematic](characters/Cinematic.png)

If you use [SillyTavern](https://github.com/SillyTavern/SillyTavern) for
character roleplay, the Guild plugs straight into it. SillyTavern keeps
doing what it does best — long-form conversation, character cards,
group chats — and offloads every "I want a picture of this" moment to
the Guild's wizards.

Your roleplay gets *eyes*: backgrounds change as the story moves,
character portraits shift with emotions, dramatic moments get
illustrated automatically. Spellcaster ships **13 SillyTavern character
cards** that map cleanly onto the Guild's wizards (Imaginus draws,
Sceneshifter rebuilds the scene background, Restyler restyles a
character mid-conversation, Cinematic stitches multi-shot animations),
so the AI in your story can call them mid-scene without you ever
leaving the chat window.

The Guild also exposes the same back end to **any other front end** that
can talk to a local LLM — OpenWebUI, LM Studio, even a Signal bot via
the **Signal Bridge**. The wizards don't care who's calling. If it
speaks LLM, it can ask the Guild to generate art.
<!-- /WIZARD_SPEECH:sillytavern -->

<!-- WIZARD_SPEECH:gimp -->
**When you want a real image editor: GIMP.**

![Inpaint demo](../assets/demo_step2_inpaint.png)

The Wizard Guild is built for *conversation* — describe what you want,
get a result. But sometimes you want pixel-level control: a selection
mask shaped exactly the way you need, a layer blend at 47% opacity,
a clone-stamp pass on a single eyelash.

That's what **GIMP** is for, and Spellcaster ships a full GIMP plugin
that mirrors every Guild wizard as a `Filters → Spellcaster …` menu
entry. You get **49 AI tools right inside GIMP**: text-to-image,
inpaint, face swap (ReActor + IPAdapter + PuLID + Klein), Klein
img2img, LTX / Wan video, SeedVR2 upscale, ControlNet, IC-Light, LUT
grading, RemBG, the full Magic Studios actor pipeline, and more.

The same scaffold drives both. The Guild is the conversational front
door; GIMP is the workshop. Bounce between them as the task demands —
chat with a wizard to get the rough composition, switch to GIMP for
the detail pass, then come back to the chat to animate the result.
<!-- /WIZARD_SPEECH:gimp -->

<!-- WIZARD_SPEECH:ready -->
**That's the tour.**

Every wizard's portrait is ready. The chat is yours. Pick a wizard
from the sidebar — they're each specialised for different work — and
just tell them what you want. They'll handle the rest.

If you ever want me back, I'm filed under *The Archivist* in the
sidebar. *Now off you go. Have fun.*
<!-- /WIZARD_SPEECH:ready -->
