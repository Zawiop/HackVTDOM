/**
 * getWorldStatePrompt (spec 04).
 *
 * The five prompt strings below are the reason output stays consistent across
 * every building and every user, so they live here and only here. The frontend
 * sends an enum; it never sends prompt text for the preset path. The single
 * exception is the freeform override, which *replaces* the locked string
 * outright — it does not append to it, wrap it, or blend with it.
 */

export const WORLD_STATES = [
  'reclaimed',
  'flooded',
  'scorched',
  'buried',
  'petrified',
] as const;

export type WorldState = (typeof WORLD_STATES)[number];

const WORLD_STATE_SET: ReadonlySet<string> = new Set(WORLD_STATES);

export function isWorldState(value: unknown): value is WorldState {
  return typeof value === 'string' && WORLD_STATE_SET.has(value);
}

/**
 * Shared visual grammar appended to nothing — it is written *into* each string
 * rather than concatenated, so each prompt reads as one coherent paragraph to
 * the image model instead of a tag soup. Keeping them whole is the point:
 * spec 04 asks for "a complete descriptive paragraph, not a short tag".
 */
const PROMPTS: Record<WorldState, string> = {
  reclaimed:
    'Transform this building into a structure that nature has spent decades taking back. ' +
    'Thick sheets of ivy and climbing vines swallow the façade, rooting in every window frame and ' +
    'cornice; moss carpets the ledges and stair treads in deep velvet green. Concrete is cracked and ' +
    'spalled, rebar showing through in rust-orange streaks, with saplings and tall grasses growing out ' +
    'of the gutters and roofline. Windows are empty or shattered, their openings dark and softened by ' +
    'leaves. Shafts of hazy sunlight cut through the canopy as visible god rays, catching drifting ' +
    'pollen and dust. Muted amber-and-green palette, desaturated and overcast-warm, with heavy ' +
    'atmospheric depth. Preserve the building\'s original silhouette, massing, window rhythm and ' +
    'footprint exactly — this is the same structure abandoned for fifty years, not a different building. ' +
    'Photorealistic, natural light, no people, no text, no signage.',

  flooded:
    'Transform this building into a structure standing in permanent floodwater. Still, opaque ' +
    'green-brown water sits partway up the ground floor, mirroring the façade in a soft broken ' +
    'reflection. A hard tide line of algae, silt and mineral staining rings the walls where the water ' +
    'once stood higher, with rust bleeding from every fixing and downpipe. Lower windows are dark and ' +
    'submerged, upper ones streaked with dried mud. Reeds, duckweed and waterlogged debris collect ' +
    'against the walls; pale aquatic growth clings below the waterline. Mist hangs over the surface and ' +
    'shafts of sunlight break through as visible god rays. Muted amber-and-green palette, desaturated, ' +
    'humid and heavy. Preserve the building\'s original silhouette, massing, window rhythm and ' +
    'footprint exactly — this is the same structure, drowned. Photorealistic, natural light, no people, ' +
    'no text, no signage.',

  scorched:
    'Transform this building into a fire-scarred ruin long after the burn. Soot-blackened walls fade ' +
    'upward into grey ash-wash; window openings are empty sockets rimmed with dark scorch plumes where ' +
    'flame once licked out. Sections of roof and floor have collapsed inward, leaving charred beams ' +
    'exposed against the sky and rubble banked at the base. Surviving metal is warped and heat-blued; ' +
    'concrete is spalled and chalk-white where it cracked from the heat. Fine ash drifts in the air and ' +
    'the first pioneer weeds push through the debris in sparse green. Low sun cuts through smoke haze ' +
    'as visible god rays. Muted amber-and-green palette over charcoal and bone-grey, desaturated and ' +
    'smoke-dimmed. Preserve the building\'s original silhouette, massing, window rhythm and footprint ' +
    'exactly — this is the same structure after the fire, not a different building. Photorealistic, ' +
    'natural light, no people, no text, no signage.',

  buried:
    'Transform this building into a structure being swallowed by the earth. Drifts of pale dust and ' +
    'silt bank high against the walls, burying the ground floor and pouring through door openings; the ' +
    'building emerges from the ground at an angle, as though the land has risen around it. Wind-carved ' +
    'ripples cross the surface of the drifts, and sediment layers stain the façade in horizontal bands ' +
    'of ochre and grey. Upper windows are half-choked with earth, lower ones gone entirely. Dry scrub ' +
    'and hardy grasses take root in the slopes. Dust hangs in the air, catching low sunlight as visible ' +
    'god rays. Muted amber-and-green palette, arid and desaturated. Preserve the building\'s original ' +
    'silhouette, massing, window rhythm and footprint exactly — this is the same structure, partly ' +
    'interred. Photorealistic, natural light, no people, no text, no signage.',

  petrified:
    'Transform this building into a structure turned to stone. Every surface has become pale mineral ' +
    'rock — calcified, matte and porous, the way wood looks after it has fossilised. Fine crystalline ' +
    'growth creeps outward from the joints and window reveals; stalactite-like mineral drips hang from ' +
    'every sill, lintel and cornice. Edges that were once sharp are rounded and fused, as if the whole ' +
    'façade slumped a fraction before hardening. Hairline fracture networks run across the stone and ' +
    'thin dry lichen crusts the north faces in grey-green. Windows are filled with opaque mineral, not ' +
    'glass. Still, dust-laden air with sunlight breaking through as visible god rays. Muted amber-and-' +
    'green palette over bone and limestone tones, desaturated and utterly static. Preserve the ' +
    'building\'s original silhouette, massing, window rhythm and footprint exactly — this is the same ' +
    'structure, mineralised. Photorealistic, natural light, no people, no text, no signage.',
};

/**
 * UI copy for the World State spectrum (spec 04's framing note: present this as
 * Present <-> Collapsed world-building, not "pick a filter").
 *
 * `blurb` is short display text only. The full prompt string is *never* included
 * here — it stays server-side so the frontend has nothing to echo back.
 */
export interface WorldStateOption {
  id: WorldState;
  label: string;
  blurb: string;
  /** 0 = nearest the present, 1 = furthest collapsed. Orders the spectrum UI. */
  spectrumPosition: number;
}

export const WORLD_STATE_OPTIONS: readonly WorldStateOption[] = [
  {
    id: 'reclaimed',
    label: 'Reclaimed',
    blurb: 'Nature takes it back — ivy, moss, saplings in the gutters.',
    spectrumPosition: 0.2,
  },
  {
    id: 'flooded',
    label: 'Flooded',
    blurb: 'Permanent water, tide lines, rust and silt.',
    spectrumPosition: 0.4,
  },
  {
    id: 'scorched',
    label: 'Scorched',
    blurb: 'Long after the burn — soot, collapse, ash in the air.',
    spectrumPosition: 0.6,
  },
  {
    id: 'buried',
    label: 'Buried',
    blurb: 'The ground rises and swallows it in drifts of silt.',
    spectrumPosition: 0.8,
  },
  {
    id: 'petrified',
    label: 'Petrified',
    blurb: 'Turned to pale mineral stone, fused and still.',
    spectrumPosition: 1.0,
  },
];

export type WorldStatePromptSource = 'preset' | 'override';

export interface WorldStatePromptResult {
  /** The single string step 05 sends to the image model. */
  prompt: string;
  source: WorldStatePromptSource;
  /** Which preset was asked for. Null when the override path was used alone. */
  worldState: WorldState | null;
}

export class InvalidWorldStateError extends Error {
  constructor(public readonly received: unknown) {
    super(
      `Unknown world state ${JSON.stringify(received)}. Expected one of: ${WORLD_STATES.join(', ')}.`,
    );
    this.name = 'InvalidWorldStateError';
  }
}

export interface GetWorldStatePromptInput {
  worldState?: string | null;
  /** Freeform user description. When non-empty it REPLACES the locked string. */
  freeformOverride?: string | null;
}

/**
 * Resolve a UI selection into the one string that goes to step 05.
 *
 * Override semantics are the whole point of spec 04: a freeform description
 * replaces the preset for that single generation. It is never appended to the
 * locked paragraph, because "describe desired changes with an AI prompt" only
 * counts if what the user typed is actually what gets sent.
 */
export function getWorldStatePrompt(
  input: GetWorldStatePromptInput,
): WorldStatePromptResult {
  const override = input.freeformOverride?.trim();
  const requested = input.worldState?.trim();
  const worldState = requested && isWorldState(requested) ? requested : null;

  if (override) {
    // A bad preset id alongside a valid override is not worth failing on — the
    // override is what gets sent either way.
    return { prompt: override, source: 'override', worldState };
  }

  if (!requested) throw new InvalidWorldStateError(input.worldState ?? null);
  if (!worldState) throw new InvalidWorldStateError(requested);

  return { prompt: PROMPTS[worldState], source: 'preset', worldState };
}

/** Direct access to a locked string. Server-side callers only. */
export function getPresetPrompt(state: WorldState): string {
  return PROMPTS[state];
}
