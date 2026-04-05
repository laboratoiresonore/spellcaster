# Spellcaster Magic Studios
## The Complete Walkthrough: A Star Is Born (Reluctantly)

*Featuring Gerald McFluffington III, CPA — Actor, Dreamer, Carb Enthusiast*

---

### Prologue: The Audition Nobody Asked For

Gerald McFluffington III has been an accountant in Peoria, Illinois for twenty-two years. He has a corner cubicle, a reliable Camry, and a cat named Spreadsheet who once yawned on camera and got 47 YouTube views (38 from Gerald's mother, 6 from Gerald himself on different devices, and 3 from a bot in Kazakhstan).

Last Tuesday, Gerald walked into **Spellcaster Magic Studios** with a crumpled 4x6 photo from a Walgreens self-serve kiosk, slapped it on the front desk, and announced:

> *"I'm here for my close-up."*

The receptionist, who had seen many things in her career but never an accountant in khakis with a motivational poster tucked under his arm ("BELIEVE IN YOUR SPREADSHEETS"), simply pointed to Studio 7.

What followed is the most thorough — and arguably most unnecessary — star-making pipeline in the history of AI-assisted cinema.

This is his story. This is also your tutorial.

---

## Act I: Casting Polaroids
### *"I'd like three shots. One serious, one mysterious, and one where I look like young Clooney."*

**Tool: Filters > Spellcaster Magic Studios > 1. Casting Polaroids (Face Model)**

Gerald hands over his Walgreens photo. It's slightly overexposed, he's blinking in it, and there's a display rack of reading glasses visible behind his left ear. Perfect source material.

**What happens:**
1. Upload Gerald's photo (or use your canvas)
2. Pick "Man" as the subject
3. Name the model: `gerald_mcfluffington`
4. Click **Generate Passport Photos**

Spellcaster's ReActor engine takes Gerald's questionable photo and produces three clean, studio-quality headshots:

| Variant #1 | Variant #2 | Variant #3 |
|:---:|:---:|:---:|
| ![Variant 1](assets/walkthrough/casting_01.png) | ![Variant 2](assets/walkthrough/casting_02.png) | ![Variant 3](assets/walkthrough/casting_03.png) |
| *CodeFormer Sharp* | *GPEN-2048 Balanced* | *CodeFormer Faithful* |

Gerald squints at all three and points at Variant #2.

> *"That one. That's the one where I look most like young Clooney."*

The casting director does not have the heart to tell him it looks most like middle-aged Gerald with better lighting. She clicks **Save This Face Model**.

A small orange warning appears:

> **The saved model will only appear in face swap dropdowns after restarting the ComfyUI server.**

Gerald asks if this is like rebooting a spreadsheet. Nobody answers.

**Gerald's face model is saved. His journey has begun.**

![Casting Complete](assets/walkthrough/casting_complete.png)

> **BEHIND THE SCENES:** The Casting Polaroids tool runs each variant through ReActorFaceSwapOpt (self-swap + restore) with ReActorFaceBoost for maximum clarity. Three different restore models ensure variety: CodeFormer (sharp), GPEN-2048 (balanced), CodeFormer (faithful). The selected image is fed to ReActorBuildFaceModel + ReActorSaveFaceModel to create a `.safetensors` face embedding.

---

## Act II: Body Double
### *"I want action hero, but approachable. Like someone who could save the world AND bring a casserole to the potluck."*

**Tool: Filters > Spellcaster Magic Studios > 2. Body Double (Full Body Ref)**

Gerald is 5'9" and what his doctor diplomatically calls "robust." The Body Factory doesn't judge. It generates.

**What happens:**
1. Gerald's face model is the reference (use canvas or upload his photo)
2. Select a generation model (SDXL recommended)
3. Pick body type: "Average build — neutral"
4. Click **Generate Bodies**

Gerald immediately changes his mind.

> *"Actually, can we try 'Muscular / Fit — male'? Not like, BODYBUILDER muscular. Like... muscular but you can tell he enjoys pasta."*

Three full-body images appear, each with Gerald's face seamlessly swapped onto a fit body, background removed for a clean transparent PNG:

| Body #1 | Body #2 | Body #3 |
|:---:|:---:|:---:|
| ![Body 1](assets/walkthrough/body_01.png) | ![Body 2](assets/walkthrough/body_02.png) | ![Body 3](assets/walkthrough/body_03.png) |
| *Fitness model build* | *Athletic casual* | *Beach-ready* |

Gerald studies them for a full three minutes.

> *"Number 2. That guy looks like he could do a push-up but would rather have a sandwich. That's my brand."*

He clicks **Use This Body**.

The transparent PNG is now his top layer in GIMP. Gerald McFluffington III has a body double, and it is glorious.

![Body Complete](assets/walkthrough/body_complete.png)

> **BEHIND THE SCENES:** Body Factory runs a three-stage pipeline: txt2img (generates body with quality-boosted prompt including "natural skin texture, visible pores, subsurface scattering"), then ReActor face swap (High quality preset: ReSwapper 256 + GPEN-2048), then rembg background removal for a clean transparent PNG. The result is ready to composite into any scene.

---

## Act III: Wardrobe Department
### *"The costume lady had OPINIONS."*

**Tool: Filters > Spellcaster Magic Studios > 3. Wardrobe Department**

Gerald is introduced to Marguerite, the AI Wardrobe Department. Marguerite, as it turns out, has very strong feelings about what Gerald should wear.

Gerald wanted a simple Hawaiian shirt. Marguerite had other plans.

**Attempt 1: "Formal — business suit"**

> Gerald: *"I look like I'm about to audit someone's taxes."*
> Marguerite: *"..."*
> Gerald: *"I mean, I DO audit people's taxes, but that's not the VIBE."*

**Attempt 2: "Fantasy — armor"**

> Gerald: *"I look like a very confused knight."*
> Marguerite: *"The breastplate really accentuates your—"*
> Gerald: *"NEXT."*

**Attempt 3: The Shark Incident**

Marguerite, it seems, had been waiting all week to deploy the custom shark costume prompt she'd been working on. Before Gerald could object, she had typed `"wearing a full-body great white shark costume, dorsal fin hat, felt shark teeth around face, ridiculous but committed"` and hit generate.

| The Shark | The Reaction | The Compromise |
|:---:|:---:|:---:|
| ![Shark](assets/walkthrough/wardrobe_shark.png) | ![Reaction](assets/walkthrough/wardrobe_reaction.png) | ![Hawaiian](assets/walkthrough/wardrobe_final.png) |
| *Marguerite's magnum opus* | *Gerald's face says it all* | *The Hawaiian shirt, finally* |

Gerald, to his credit, posed for the shark photo. He even did the fin shake.

> *"She kept spraying me with a water bottle and asking me to 'make the fins angrier.' I don't even know what that means. Do sharks have angry fins? Is that a thing? I'm an accountant."*

Eventually, they compromised on:

**"Casual — jeans & t-shirt"** with a custom modification: `"wearing casual blue jeans, a bright Hawaiian shirt with palm tree print, open collar, relaxed vacation style"`

Gerald is satisfied. Marguerite is not, but she has learned to pick her battles.

**What actually happens in the tool:**
1. Select the clothing area with GIMP's Free Select tool
2. Pick the Klein model (9B for quality)
3. Choose an outfit preset (or type custom like Gerald)
4. Set change strength to 0.85
5. Click **Try On Outfit**

![Wardrobe Complete](assets/walkthrough/wardrobe_complete.png)

> **BEHIND THE SCENES:** The Clothing Store uses Klein Flux 2 inpaint with DifferentialDiffusion for smooth edges. Your GIMP selection defines the clothing area. The AI replaces ONLY the selected region while preserving face, body shape, pose, and background. Low denoise (0.30-0.50) for color changes, high (0.85+) for full outfit replacement.

---

## Act IV: Set Design
### *"Every great actor needs fog. Name ONE great actor who didn't have fog."*

**Tool: Filters > Spellcaster Magic Studios > 4. Set Design (Scene Compositor)**

The producer wanted a simple beach sunset. Gerald had notes.

> *"I want a beach. But MOODY. Like the beach is contemplating its existence. And fog. Lots of fog. Name one great actor who didn't have fog in at least one scene. You can't. I'll wait."*

The assistant Googled it. He could name several. He chose not to.

**Step 1: Generate the background**

Select: `"Outdoor — beach"` and modify the prompt to add Gerald's artistic vision:

*"tropical beach scene, palm trees, turquoise ocean, golden sand, sunset lighting, photorealistic, **rolling fog, mysterious atmosphere, moody cinematic**"*

Three backgrounds appear:

| BG #1 | BG #2 | BG #3 |
|:---:|:---:|:---:|
| ![BG 1](assets/walkthrough/set_bg_01.png) | ![BG 2](assets/walkthrough/set_bg_02.png) | ![BG 3](assets/walkthrough/set_bg_03.png) |
| *Too sunny (Gerald disapproves)* | *Fog: approved* | *"Too much fog, even for me"* |

Gerald picks #2. *"That's the fog of a man with a Hawaiian shirt and a STORY."*

**Step 2: Place Gerald in the scene**

Select Gerald's transparent body PNG as Actor 1, placement: "Center — standing"

Klein Flux 2 harmonizes Gerald into the sunset, matching the warm lighting on his skin, casting a shadow that makes him look 10% more dramatic than he has any right to.

| Composite Result |
|:---:|
| ![Set Complete](assets/walkthrough/set_complete.png) |
| *Gerald McFluffington III. On a foggy beach. In a Hawaiian shirt. Cinema.* |

> *"I just got chills. Is that the fog or is that me being MOVED by my own presence? Don't answer that."*

![Set Final](assets/walkthrough/set_final.png)

> **BEHIND THE SCENES:** Studio Set generates backgrounds via txt2img with quality-boosted prompts, then composites each actor using Klein Flux 2 blend at low denoise (0.30) to harmonize lighting, shadows, and color temperature. Each actor is processed sequentially — the result of Actor 1 becomes the background for Actor 2, and so on.

---

## Act V: The Director's Chair
### *"I've been preparing for this role my entire life. Well, since Tuesday."*

**Tool: Filters > Spellcaster Magic Studios > 5. Director's Chair (Solo)**

This is it. Gerald's big scene. The one they'll show at the Oscars before his lifetime achievement award (projected timeline: 2047, he's optimistic).

**The Scene:** Gerald walks toward the camera on the foggy beach, pauses, does a slow-motion hair flip (he's bald — the wind catches nothing but vibes), and delivers his catchphrase directly to camera.

The director (you) selects: **"GUIDE: Walk Across Screen (FLF)"**

The instruction panel lights up:

```
MOTION DIRECTION — Make your character walk across the screen.

HOW TO USE (do this BEFORE clicking Generate):
  1. Your canvas is the START frame (Gerald on the left)
  2. Duplicate the layer (Layer > Duplicate Layer)
  3. Use the Move tool to slide Gerald to the RIGHT
  4. Flatten (Image > Flatten Image)
  5. Export this as your END frame (File > Export As > PNG)
  6. Undo back to the original
  7. Run this script — Step 1 will ask for the end frame file

Wan will animate Gerald walking from left to right!
```

Gerald reads the instructions.

> *"So I just... move myself in the picture? And the AI makes me WALK? Like, with legs and everything?"*

Yes, Gerald. With legs and everything.

**The Director's settings:**
- Script: "GUIDE: Walk Across Screen (FLF)" (modified to 2 steps)
- Turbo: ON (2H + 4L quality split)
- Shift: 8.0 (good for walking motion)
- Face re-injection: ON (Gerald's face must survive)
- RIFE 4x interpolation: ON
- RTX 2.5x upscale: ON

**Step 1: The Walk (FLF)**
Gerald walks toward camera through the fog. His Hawaiian shirt billows. The sunset catches every palm tree. It's objectively the most cinematic thing to ever happen to a CPA from Peoria.

**Step 2: The Catchphrase (I2V)**
Gerald stops, faces the camera, and with all the gravitas of a man who has reconciled seventeen fiscal years of expense reports, he says:

*(The prompt: "person stopping, facing camera, confident expression, slight smile, dramatic pause, Hawaiian shirt, foggy beach sunset, cinematic close-up")*

| Walking | The Pause | The Look |
|:---:|:---:|:---:|
| ![Walk](assets/walkthrough/director_walk.png) | ![Pause](assets/walkthrough/director_pause.png) | ![Look](assets/walkthrough/director_look.png) |
| *Approaching through the fog* | *The dramatic stop* | *The face that launched 47 views* |

The final MP4 is saved in ComfyUI's output folder. Gerald watches it seventeen times in a row.

> *"Can we add explosions? Every great movie has explosions."*

No, Gerald. The fog is enough.

> *"...what about just a SMALL explosion? In the background? Very tasteful?"*

We select the "VFX — explosion shockwave" preset for a third step. Gerald gets his explosion. It is not small. It is not tasteful. It is perfect.

![Director Complete](assets/walkthrough/director_complete.png)

> **BEHIND THE SCENES:** The Director uses Wan 2.2's dual-model architecture (HIGH noise + LOW noise) with LightX2V turbo acceleration. FLF mode (WanFirstLastFrameToVideo) animates between your start and end frames. Face re-injection runs ReActor between steps to prevent identity drift. The final pipeline: generate → face swap → RIFE 4x interpolation (float16) → RTX Video Super Resolution → H.264 MP4 encode.

---

## Epilogue: The Premiere

Gerald's video premiered at his company's quarterly meeting, where it played between the Q3 revenue slides and the new PTO policy announcement.

It received a standing ovation from Linda in Accounts Receivable (she was standing up to get more coffee, but Gerald counted it).

His mother watched it 38 times.

Spreadsheet the cat was unimpressed.

The fog, however, was magnificent.

---

## Technical Reference

### The Complete Spellcaster Magic Studios Pipeline

```
Selfie/Photo
    │
    ▼
┌─────────────────────────────────────┐
│  1. CASTING POLAROIDS               │
│  ReActor self-swap + 3 restore      │
│  variants → save .safetensors model │
└───────────────┬─────────────────────┘
                │ face model
                ▼
┌─────────────────────────────────────┐
│  2. BODY DOUBLE                     │
│  txt2img body + ReActor face swap   │
│  + rembg → transparent PNG          │
└───────────────┬─────────────────────┘
                │ actor PNG
                ▼
┌─────────────────────────────────────┐
│  3. WARDROBE DEPARTMENT             │
│  Klein Flux 2 inpaint on clothing   │
│  region → dressed character         │
└───────────────┬─────────────────────┘
                │ dressed actor
                ▼
┌─────────────────────────────────────┐
│  4. SET DESIGN                      │
│  txt2img background + Klein blend   │
│  composite → scene with actors      │
└───────────────┬─────────────────────┘
                │ start image
                ▼
┌─────────────────────────────────────┐
│  5/6/7. DIRECTOR'S CHAIR            │
│  Wan 2.2 I2V/FLF/Loop multi-step   │
│  + face re-injection + RIFE + RTX   │
│  → final MP4 video                  │
└─────────────────────────────────────┘
```

### What You Need

| Component | Requirement |
|-----------|-------------|
| **GIMP** | Version 3.0+ |
| **ComfyUI** | Running on local or network GPU |
| **Spellcaster** | Installed via the installer |
| **GPU (server)** | 8GB+ VRAM (16GB recommended) |
| **Models** | At least one checkpoint (SDXL/Flux) |
| **Custom Nodes** | ReActor, VHS, RIFE VFI, RTX (optional) |

### Gerald's Final Words

> *"If I can do this, anyone can. I didn't even know what a LoRA was until Tuesday. I thought it was a name. Like, 'Hey Lora, can you pass the stapler?' Turns out it's a neural network weight modification technique. Who knew?"*
>
> *"Anyway, my next project is a five-part epic about an accountant who saves the world using only a TI-84 calculator and the power of compound interest. Working title: 'The Auditor.' Marguerite already has a shark costume ready for the underwater scene."*
>
> *"I didn't ask for an underwater scene."*

---

*Spellcaster Magic Studios is part of the [Spellcaster](https://github.com/laboratoiresonore/spellcaster) project by Laboratoire Sonore.*

*No accountants were harmed in the making of this walkthrough. Gerald's Hawaiian shirt, however, will never be the same.*
