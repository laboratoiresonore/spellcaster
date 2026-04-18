// starter_chips.js — plain-English entry chips for each wizard + universal
// image action chips that appear below every generated image.
//
// No jargon. No technical terms. Each chip sends a natural English phrase
// to the LLM exactly as if the user had typed it, so all existing scaffold
// routing works unchanged.

// ── Per-wizard starter chips ──
// Key = wizard id (character.id). Up to 5 chips per wizard.
const STARTER_CHIPS = {
    // Image Generation
    "studio_imaginus": [
        { icon: "✨", label: "Create a new image",  message: "I want to make a brand new image from scratch." },
        { icon: "🎨", label: "Make a portrait",     message: "I want to make a portrait of a character." },
        { icon: "🏞️", label: "Paint a landscape",   message: "I want to paint a landscape." },
        { icon: "🎲", label: "Surprise me",         message: "Show me what you can do — surprise me with something creative." },
    ],
    // Image Transformation
    "studio_transmutex": [
        { icon: "🎨", label: "Change the style",    message: "I want to change the visual style of an image." },
        { icon: "🖌️", label: "Make it look painted", message: "Make an image look like a painting." },
        { icon: "✨", label: "Add more detail",     message: "Take an image and add more detail and richness." },
        { icon: "🌈", label: "Change the mood",     message: "Change the mood and atmosphere of an image." },
    ],
    // Face & Identity
    "studio_masquerade": [
        { icon: "👤", label: "Put my face on a photo",    message: "I want to put my face onto someone in another photo." },
        { icon: "👥", label: "Keep identity, new scene",  message: "Keep the same person's face but put them in a different scene." },
        { icon: "🎭", label: "Generate a lookalike",      message: "Generate an image that looks like a specific person." },
    ],
    // Upscale & Restoration
    "studio_restorix": [
        { icon: "✨", label: "Make it bigger",            message: "I want to upscale an image to a higher resolution." },
        { icon: "📷", label: "Fix an old photo",          message: "I have an old or damaged photo I want to restore." },
        { icon: "🔍", label: "Add more detail",           message: "Take an image and hallucinate more detail into it." },
    ],
    // Inpaint / Removal
    "studio_erasure": [
        { icon: "✂️", label: "Remove something",          message: "I want to remove an object from a photo." },
        { icon: "🧹", label: "Clean up the background",   message: "Clean up the background of a photo." },
        { icon: "🖼️", label: "Fix a blemish",             message: "Fix a small blemish or imperfection in a photo." },
    ],
    // Video Generation
    "studio_videomancer": [
        { icon: "🎬", label: "Bring a photo to life",     message: "I want to animate a still photo into a short video." },
        { icon: "🔁", label: "Make a short loop",         message: "Create a short looping video." },
        { icon: "💨", label: "Add subtle motion",         message: "Add subtle, gentle motion to an image." },
    ],
    // Cinematic / multi-shot
    "studio_cinematic": [
        { icon: "🎥", label: "Build a scene",             message: "Help me build a multi-shot scene from a single concept." },
        { icon: "🎞️", label: "Tell a story",              message: "Tell a short visual story in several shots." },
        { icon: "🎬", label: "Create a short ad",         message: "Make a short ad-style sequence." },
    ],
    // Magic Studios pipeline
    "studio_studiocraft": [
        { icon: "🎬", label: "Full character pipeline",   message: "I want to build a full character — face, body, outfit, scene." },
        { icon: "📷", label: "Casting polaroids",         message: "Make reusable casting polaroids of a character for later use." },
        { icon: "👕", label: "Try on different outfits",  message: "Try a character in different outfits." },
    ],
    // First-run guide (Archivist) — no chips, setup is linear
    "studio_archivist": [],

    // Whimsy Weaver — LTX2 video
    "model_ltx2": [
        { icon: "🎬", label: "Bring a photo to life",     message: "I want to animate a still photo." },
        { icon: "📝", label: "Video from a description",  message: "Make a short video from a text description." },
        { icon: "🔁", label: "Make it loop smoothly",     message: "Create a smooth looping video." },
    ],
    // Enigma — misc
    "model_misc": [
        { icon: "🎲", label: "Surprise me",               message: "Show me what you can do." },
        { icon: "🔧", label: "Run a custom workflow",     message: "I want to run a custom workflow." },
    ],

    // ── Fallback for per-model wizards (comfyui_*) ──
    "_per_model_default": [
        { icon: "🎨", label: "Make an image",             message: "Make an image using this model." },
        { icon: "🎲", label: "Show me what you can do",   message: "Show me an example of what this model is good at." },
        { icon: "🖼️", label: "Copy a reference",          message: "Take a reference image and make something similar in this model's style." },
    ],
};

// ── Universal image action chips ──
// Rendered below every generated image. Clicking either switches to the
// target wizard (with the image attached as context) or fires a canned
// message on the current wizard.
//
// Target wizard = switch. If null, stay on current wizard.
const IMAGE_ACTION_CHIPS = [
    {
        icon: "🎨",
        label: "Restyle",
        targetWizard: "studio_transmutex",
        message: "I want to restyle this image — change the look and feel.",
    },
    {
        icon: "✨",
        label: "Make it bigger",
        targetWizard: "studio_restorix",
        message: "I want to upscale this image and add more detail.",
    },
    {
        icon: "✂️",
        label: "Erase something",
        targetWizard: "studio_erasure",
        message: "I want to remove something from this image.",
    },
    {
        icon: "🎬",
        label: "Animate it",
        targetWizard: "studio_videomancer",
        message: "I want to bring this image to life as a short video.",
    },
];

// Overflow menu (behind the "⋯ More" chip)
const IMAGE_ACTION_OVERFLOW = [
    {
        icon: "👤",
        label: "Swap a face",
        targetWizard: "studio_masquerade",
        message: "I want to use this image for a face swap.",
    },
    {
        icon: "🔍",
        label: "Smart select something",
        targetWizard: "studio_erasure",
        message: "Let me point at something in this image and select it automatically.",
    },
    {
        icon: "🖼️",
        label: "Use as reference",
        targetWizard: null,  // stay on current wizard
        message: "Use this image as a reference for what I want next.",
    },
    {
        icon: "💾",
        label: "Save to disk",
        targetWizard: null,  // handled specially — just downloads
        message: "__DOWNLOAD__",
    },
];

function getStarterChips(wizardId) {
    if (!wizardId) return [];
    if (STARTER_CHIPS[wizardId]) return STARTER_CHIPS[wizardId];
    // Per-model wizards auto-generated from ComfyUI checkpoints
    if (wizardId.startsWith("comfyui_")) return STARTER_CHIPS["_per_model_default"];
    return [];
}

function getImageActionChips() {
    return IMAGE_ACTION_CHIPS;
}

function getImageActionOverflow() {
    return IMAGE_ACTION_OVERFLOW;
}

// Expose globally for app.js
window.getStarterChips = getStarterChips;
window.getImageActionChips = getImageActionChips;
window.getImageActionOverflow = getImageActionOverflow;
