"""Still-image prompts for tools/render_lore_sample.py."""

# Establishing-shot prompts keyed to each cold open's imagery. FLUX; period, no lettering.
STYLE = ("Cinematic, painterly, muted natural light, shallow depth of field, historically "
         "accurate, atmospheric, highly detailed, no text, no lettering, no watermark, no people "
         "facing camera")

PROMPTS = {
    "silkroad": [
        "A ruined Han dynasty mud-brick watchtower half-buried in the pale sand of the Gobi "
        "desert at dawn, long shadows, empty vast landscape",
        "A bundle of ancient folded paper letters tied with cord, resting on weathered wood, "
        "close up, soft archival light",
        "A distant Bactrian camel caravan crossing an immense empty desert under a huge sky, "
        "tiny figures, golden afternoon haze",
        "An oasis town of flat mud-brick buildings beside a green strip of poplar trees on the "
        "edge of a desert, late day",
        "A dim carved Buddhist cave shrine at Dunhuang, faded murals on the walls, shaft of "
        "light through the entrance",
        "A quiet Tang dynasty market street at dusk with bolts of silk stacked under awnings, "
        "lanterns just lit",
    ],
    "blackdeath": [
        "Twelve medieval Genoese galleys riding low in a Sicilian harbour at grey dawn, still "
        "water, October 1347, overcast sky",
        "A narrow deserted medieval stone street in a southern Italian town, shuttered windows, "
        "pale morning light",
        "A snow-dusted Central Asian mountain valley with marmot burrows among rocks and sparse "
        "grass, cold clear light",
        "A medieval Italian town square seen from above, empty, long shadows, terracotta roofs, "
        "still and quiet",
        "An old parchment town ordinance document with a wax seal on a wooden table, candlelight, "
        "close up",
        "A walled medieval hilltop town in Tuscany at dusk, cypress trees, muted colours, no "
        "people",
    ],
    "mongol": [
        "The vast green Mongolian steppe under an enormous sky, distant felt yurts, herds of "
        "horses, summer light",
        "An ornate silver fountain shaped like a tree inside a grand medieval hall, dim golden "
        "light, richly detailed metalwork",
        "A lone Mongol relay rider galloping across open grassland at speed, low sun, dust "
        "trailing behind",
        "A carved medieval metal passport tablet with inscription resting on dark cloth, close "
        "up, museum lighting",
        "A large medieval Central Asian walled city on a plain seen from a distance at golden "
        "hour, walls and towers",
        "A cluster of white felt gers on the steppe at dusk with smoke rising, mountains behind, "
        "calm evening",
    ],
}

FULL_STILL_PROMPT = ("Create one quiet, non-graphic historical establishing shot from the narration excerpt below. "
                     "Choose its single most concrete named person, place, object, or action; do not combine different "
                     "moments into a collage. Narration excerpt: {excerpt}")
