"""
core/protocol_templates.py

Validated protocol templates library for AuroLab.
8 common lab assays with pre-validated parameters, reagents, and steps.
Templates can be customised (sample count, concentration, plate format)
and fed directly into the LLM generator for enriched output.

Templates are NOT static — they provide structured hints that get merged
with RAG retrieval to produce a fully cited, robot-executable protocol.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class TemplateParameter:
    """A configurable parameter in a template."""
    name:         str
    label:        str
    default:      Any
    unit:         str      = ""
    min_val:      Any      = None
    max_val:      Any      = None
    choices:      list     = field(default_factory=list)
    description:  str      = ""
    param_type:   str      = "number"   # number | choice | text | bool


@dataclass
class ProtocolTemplate:
    """
    A validated protocol template for a common lab assay.
    Parameters are user-configurable; the rest is fixed domain knowledge.
    """
    template_id:    str
    name:           str
    category:       str               # assay | prep | analysis | qc
    description:    str
    tags:           list[str]         = field(default_factory=list)
    parameters:     list[TemplateParameter] = field(default_factory=list)
    reagents:       list[str]         = field(default_factory=list)
    equipment:      list[str]         = field(default_factory=list)
    estimated_time_min: int           = 60
    difficulty:     str               = "medium"  # easy | medium | hard
    safety_level:   str               = "safe"
    references:     list[str]         = field(default_factory=list)
    hint_steps:     list[str]         = field(default_factory=list)

    def build_instruction(self, params: dict) -> str:
        """Build a natural language instruction using configured parameters."""
        p = {tp.name: params.get(tp.name, tp.default) for tp in self.parameters}
        return self._instruction_template.format(**p)

    def to_dict(self) -> dict:
        return {
            "template_id":        self.template_id,
            "name":               self.name,
            "category":           self.category,
            "description":        self.description,
            "tags":               self.tags,
            "parameters":         [
                {"name": p.name, "label": p.label, "default": p.default,
                 "unit": p.unit, "min_val": p.min_val, "max_val": p.max_val,
                 "choices": p.choices, "description": p.description,
                 "param_type": p.param_type}
                for p in self.parameters
            ],
            "reagents":           self.reagents,
            "equipment":          self.equipment,
            "estimated_time_min": self.estimated_time_min,
            "difficulty":         self.difficulty,
            "safety_level":       self.safety_level,
            "references":         self.references,
            "hint_steps":         self.hint_steps,
        }


# ---------------------------------------------------------------------------
# Template library — 8 common assays
# ---------------------------------------------------------------------------

BCA_ASSAY = ProtocolTemplate(
    template_id="bca_protein_assay",
    name="BCA Protein Assay",
    category="assay",
    description="Quantify total protein concentration using bicinchoninic acid (BCA) colorimetric detection at 562 nm. Compatible with most detergents.",
    tags=["protein", "quantification", "colorimetric", "96-well"],
    parameters=[
        TemplateParameter("n_samples", "Number of samples", 8, "", 1, 96,
                          description="How many unknown samples to quantify", param_type="number"),
        TemplateParameter("sample_volume_ul", "Sample volume", 25, "µL", 1, 100,
                          description="Volume of each sample to add to the assay"),
        TemplateParameter("incubation_temp_c", "Incubation temperature", 37, "°C", 25, 60,
                          description="37°C standard; 60°C for faster protocol"),
        TemplateParameter("incubation_time_min", "Incubation time", 30, "min", 15, 120,
                          description="30 min at 37°C is standard"),
        TemplateParameter("standard_curve", "BSA standard curve", "2000-25",
                          description="Top and bottom concentrations in µg/mL",
                          param_type="choice",
                          choices=["2000-25", "2000-125", "1000-62.5"]),
        TemplateParameter("plate_format", "Plate format", "96-well", "",
                          choices=["96-well", "384-well", "microcentrifuge"],
                          param_type="choice"),
    ],
    reagents=[
        "BCA Protein Assay Reagent A (Pierce/Thermo)",
        "BCA Protein Assay Reagent B (Pierce/Thermo)",
        "BSA Standard (2 mg/mL stock)",
        "PBS or sample diluent",
    ],
    equipment=[
        "96-well flat bottom plate",
        "Multichannel pipette P300",
        "Plate reader (562 nm filter)",
        "Incubator or heat block",
        "Microcentrifuge",
    ],
    estimated_time_min=75,
    difficulty="easy",
    safety_level="safe",
    references=[
        "Smith et al. (1985) Anal. Biochem. 150:76-85",
        "Thermo Scientific Pierce BCA Protein Assay Kit manual",
    ],
    hint_steps=[
        "Prepare BSA standard curve: 8 dilutions from top concentration to zero",
        "Add {sample_volume_ul} µL of each sample and standard to wells in duplicate",
        "Add 200 µL of BCA Working Reagent (50:1 Reagent A:B) to each well",
        "Mix plate on plate shaker for 30 seconds",
        "Incubate at {incubation_temp_c}°C for {incubation_time_min} minutes",
        "Cool plate to room temperature (5 min)",
        "Read absorbance at 562 nm on plate reader",
        "Calculate protein concentration from standard curve",
    ],
)
BCA_ASSAY._instruction_template = (
    "Perform a BCA protein assay on {n_samples} samples using a {plate_format} plate. "
    "Use {sample_volume_ul} µL of each sample. Incubate at {incubation_temp_c}°C for "
    "{incubation_time_min} minutes. Include a BSA standard curve ({standard_curve} µg/mL). "
    "Read absorbance at 562 nm."
)


PCR_STANDARD = ProtocolTemplate(
    template_id="standard_pcr",
    name="Standard PCR",
    category="assay",
    description="Amplify a target DNA sequence using Taq or high-fidelity polymerase with standard 3-step thermocycling.",
    tags=["PCR", "DNA", "amplification", "thermocycler"],
    parameters=[
        TemplateParameter("amplicon_size_bp", "Expected amplicon size", 500, "bp", 50, 10000),
        TemplateParameter("cycles", "Number of cycles", 35, "", 20, 45),
        TemplateParameter("annealing_temp_c", "Annealing temperature", 58, "°C", 45, 72),
        TemplateParameter("extension_time_s", "Extension time", 30, "sec", 10, 600,
                          description="Rule of thumb: 1 kb/min for Taq, 30 sec/kb for Phusion"),
        TemplateParameter("template_ng", "Template DNA amount", 50, "ng", 1, 500),
        TemplateParameter("reaction_volume_ul", "Reaction volume", 25, "µL",
                          choices=[10, 25, 50], param_type="choice"),
        TemplateParameter("polymerase", "Polymerase", "Taq",
                          choices=["Taq", "Phusion", "Q5", "KOD"], param_type="choice"),
        TemplateParameter("n_reactions", "Number of reactions", 8, "", 1, 96),
    ],
    reagents=[
        "Taq or high-fidelity polymerase (2× master mix)",
        "Forward primer (10 µM)",
        "Reverse primer (10 µM)",
        "Template DNA",
        "Nuclease-free water",
        "dNTP mix (10 mM each)",
    ],
    equipment=[
        "Thermocycler",
        "PCR tubes or 96-well PCR plate",
        "PCR strip caps or adhesive film",
        "Ice bucket",
        "Vortex mixer",
        "Mini centrifuge",
    ],
    estimated_time_min=120,
    difficulty="easy",
    safety_level="safe",
    references=[
        "Mullis et al. (1986) Cold Spring Harb. Symp. Quant. Biol. 51:263-273",
        "NEB Taq PCR Protocol",
    ],
    hint_steps=[
        "Prepare master mix on ice: 2× buffer, dNTPs, primers, polymerase, water",
        "Aliquot {reaction_volume_ul} µL master mix into each PCR tube",
        "Add {template_ng} ng template DNA to each tube",
        "Seal tubes and briefly centrifuge",
        "Run thermocycler: 95°C 3min → [{cycles}× (95°C 30s → {annealing_temp_c}°C 30s → 72°C {extension_time_s}s)] → 72°C 5min → 4°C hold",
        "Verify amplification on 1% agarose gel",
    ],
)
PCR_STANDARD._instruction_template = (
    "Run a standard {cycles}-cycle PCR for a {amplicon_size_bp} bp amplicon using "
    "{polymerase} polymerase. Annealing temperature {annealing_temp_c}°C, extension "
    "{extension_time_s} seconds. Template: {template_ng} ng. Reaction volume: "
    "{reaction_volume_ul} µL. Prepare {n_reactions} reactions."
)


BRADFORD_ASSAY = ProtocolTemplate(
    template_id="bradford_assay",
    name="Bradford Protein Assay",
    category="assay",
    description="Rapid protein quantification using Bradford reagent (Coomassie G-250). Incompatible with high concentrations of detergents. Reads at 595 nm.",
    tags=["protein", "quantification", "bradford", "coomassie"],
    parameters=[
        TemplateParameter("n_samples", "Number of samples", 8, "", 1, 48),
        TemplateParameter("sample_volume_ul", "Sample volume", 5, "µL", 1, 20),
        TemplateParameter("bradford_volume_ul", "Bradford reagent volume", 250, "µL", 150, 300),
        TemplateParameter("incubation_min", "Incubation time", 5, "min", 5, 60),
    ],
    reagents=[
        "Bradford reagent (Bio-Rad or equivalent)",
        "BSA standard (1 mg/mL stock)",
        "Distilled water",
    ],
    equipment=[
        "96-well flat bottom plate",
        "Plate reader (595 nm filter)",
        "Multichannel pipette P300",
    ],
    estimated_time_min=30,
    difficulty="easy",
    safety_level="safe",
    references=["Bradford (1976) Anal. Biochem. 72:248-254"],
    hint_steps=[
        "Pipette {sample_volume_ul} µL of samples and BSA standards into wells",
        "Add {bradford_volume_ul} µL Bradford reagent to each well",
        "Mix by pipetting and incubate {incubation_min} minutes at room temperature",
        "Read absorbance at 595 nm",
    ],
)
BRADFORD_ASSAY._instruction_template = (
    "Perform a Bradford protein assay on {n_samples} samples. Add {sample_volume_ul} µL "
    "sample + {bradford_volume_ul} µL Bradford reagent per well. Incubate {incubation_min} "
    "minutes. Read at 595 nm."
)


ELISA_SANDWICH = ProtocolTemplate(
    template_id="sandwich_elisa",
    name="Sandwich ELISA",
    category="assay",
    description="Quantitative detection of target antigen using capture and detection antibodies with enzymatic HRP/TMB colorimetric readout.",
    tags=["ELISA", "immunoassay", "antibody", "HRP", "TMB"],
    parameters=[
        TemplateParameter("n_samples", "Number of samples", 16, "", 1, 88),
        TemplateParameter("sample_dilution", "Sample dilution factor", 2, "×", 1, 1000),
        TemplateParameter("capture_ab_conc_ugml", "Capture antibody concentration", 2, "µg/mL"),
        TemplateParameter("coating_volume_ul", "Coating volume per well", 100, "µL", 50, 200),
        TemplateParameter("blocking_time_h", "Blocking time", 1, "hours", 0.5, 2),
        TemplateParameter("primary_ab_dilution", "Primary antibody dilution", 1000, "×"),
        TemplateParameter("secondary_ab_dilution", "Secondary antibody (HRP) dilution", 5000, "×"),
        TemplateParameter("tmb_incubation_min", "TMB incubation time", 15, "min", 5, 30),
    ],
    reagents=[
        "Capture antibody",
        "Detection (HRP-conjugated) antibody",
        "Recombinant antigen standard",
        "Coating buffer (PBS or carbonate pH 9.6)",
        "Blocking buffer (1-3% BSA or 5% non-fat milk in PBST)",
        "PBST wash buffer (PBS + 0.05% Tween-20)",
        "HRP substrate (TMB)",
        "Stop solution (1M H₂SO₄)",
    ],
    equipment=[
        "96-well ELISA plate (high binding)",
        "Multichannel pipette P200",
        "Plate washer or multichannel for washes",
        "Plate reader (450 nm, 570 nm reference)",
        "37°C incubator",
        "Plate sealer/parafilm",
    ],
    estimated_time_min=300,
    difficulty="medium",
    safety_level="warning",
    references=["Engvall & Perlmann (1971) Immunochemistry 8:871-874"],
    hint_steps=[
        "Coat plate with {coating_volume_ul} µL capture antibody ({capture_ab_conc_ugml} µg/mL) overnight at 4°C",
        "Wash 3× with PBST",
        "Block with 300 µL blocking buffer for {blocking_time_h} hour(s) at RT",
        "Wash 3× with PBST",
        "Add {n_samples} samples (1:{sample_dilution} dilution) + standards, 100 µL/well, 2h at RT",
        "Wash 5× with PBST",
        "Add detection antibody (1:{secondary_ab_dilution}), 100 µL/well, 1h at RT",
        "Wash 5× with PBST",
        "Add TMB substrate, incubate {tmb_incubation_min} min in dark",
        "Add stop solution, read at 450/570 nm immediately",
    ],
)
ELISA_SANDWICH._instruction_template = (
    "Perform a sandwich ELISA on {n_samples} samples (1:{sample_dilution} dilution). "
    "Coat with capture antibody at {capture_ab_conc_ugml} µg/mL. "
    "Block for {blocking_time_h}h. Use detection antibody at 1:{secondary_ab_dilution}. "
    "TMB incubation: {tmb_incubation_min} min. Read at 450 nm."
)


MTT_ASSAY = ProtocolTemplate(
    template_id="mtt_cell_viability",
    name="MTT Cell Viability Assay",
    category="assay",
    description="Measure cell metabolic activity (viability/proliferation) using MTT tetrazolium reduction to formazan. OD 570 nm.",
    tags=["cell viability", "MTT", "cytotoxicity", "proliferation"],
    parameters=[
        TemplateParameter("n_samples", "Number of conditions", 6, "", 1, 12),
        TemplateParameter("n_replicates", "Replicates per condition", 4, "", 2, 8),
        TemplateParameter("cells_per_well", "Cells per well", 5000, "cells", 1000, 50000),
        TemplateParameter("treatment_time_h", "Treatment duration", 24, "hours", 1, 96),
        TemplateParameter("mtt_conc_mgml", "MTT concentration", 0.5, "mg/mL"),
        TemplateParameter("mtt_incubation_h", "MTT incubation time", 4, "hours", 2, 6),
    ],
    reagents=[
        "MTT reagent (3-(4,5-dimethylthiazol-2-yl)-2,5-diphenyltetrazolium bromide)",
        "DMSO (formazan solubilisation)",
        "Cell culture medium (DMEM/RPMI)",
        "Test compounds/treatments",
        "PBS",
    ],
    equipment=[
        "96-well flat bottom tissue culture plate",
        "CO₂ incubator (37°C, 5% CO₂)",
        "Plate reader (570 nm, 630 nm reference)",
        "Multichannel pipette",
        "Biosafety cabinet",
    ],
    estimated_time_min=360,
    difficulty="medium",
    safety_level="safe",
    references=["Mosmann (1983) J. Immunol. Methods 65:55-63"],
    hint_steps=[
        "Seed {cells_per_well} cells/well in 100 µL medium, incubate overnight",
        "Add treatments to wells in {n_replicates} replicates, incubate {treatment_time_h}h",
        "Add 10 µL MTT ({mtt_conc_mgml} mg/mL in PBS) per well",
        "Incubate {mtt_incubation_h}h at 37°C, 5% CO₂",
        "Remove medium carefully, add 100 µL DMSO per well",
        "Shake plate 10 min to dissolve formazan",
        "Read absorbance at 570 nm (reference 630 nm)",
    ],
)
MTT_ASSAY._instruction_template = (
    "Run an MTT cell viability assay on {n_samples} conditions with {n_replicates} replicates. "
    "Seed {cells_per_well} cells per well. Treat for {treatment_time_h} hours. "
    "Add MTT at {mtt_conc_mgml} mg/mL, incubate {mtt_incubation_h}h. Solubilise in DMSO. "
    "Read at 570/630 nm."
)


WESTERN_BLOT_TRANSFER = ProtocolTemplate(
    template_id="western_blot_transfer",
    name="Western Blot — SDS-PAGE & Transfer",
    category="analysis",
    description="Separate proteins by SDS-PAGE and transfer to nitrocellulose or PVDF membrane for immunodetection.",
    tags=["western blot", "SDS-PAGE", "protein", "membrane", "transfer"],
    parameters=[
        TemplateParameter("gel_percentage", "Acrylamide percentage", 10, "%", 6, 18,
                          choices=[6, 8, 10, 12, 15], param_type="choice"),
        TemplateParameter("protein_range_kda", "Target protein range", "15-250",
                          choices=["10-100", "15-250", "10-70", "50-250"], param_type="choice"),
        TemplateParameter("sample_ug", "Protein per lane", 20, "µg", 5, 50),
        TemplateParameter("transfer_time_min", "Transfer time", 60, "min", 30, 120),
        TemplateParameter("blocking_agent", "Blocking agent", "5% non-fat milk",
                          choices=["5% non-fat milk", "3% BSA", "Odyssey blocking buffer"],
                          param_type="choice"),
        TemplateParameter("membrane_type", "Membrane", "PVDF",
                          choices=["PVDF", "nitrocellulose"], param_type="choice"),
    ],
    reagents=[
        "Acrylamide/bis-acrylamide (30% stock)",
        "SDS running buffer (Tris-glycine-SDS)",
        "Transfer buffer (Tris-glycine + 20% methanol)",
        "Protein ladder",
        "Laemmli sample buffer (4× or 2×)",
        "DTT or β-mercaptoethanol (reducing agent)",
        "Methanol (PVDF activation)",
        "Ponceau S stain",
    ],
    equipment=[
        "SDS-PAGE gel system (Mini-PROTEAN or equivalent)",
        "Western blot transfer system (wet or semi-dry)",
        "PVDF or nitrocellulose membrane",
        "Power supply",
        "Rocking platform",
    ],
    estimated_time_min=240,
    difficulty="hard",
    safety_level="warning",
    references=["Towbin et al. (1979) PNAS 76:4350-4354"],
    hint_steps=[
        "Prepare {gel_percentage}% SDS-PAGE gel, allow to polymerise 30 min",
        "Denature samples: mix with Laemmli buffer, heat 95°C for 5 min",
        "Load {sample_ug} µg protein + ladder per lane",
        "Run at 150V until dye front reaches bottom (~50-60 min)",
        "Activate PVDF membrane in methanol (30 sec) if using PVDF",
        "Assemble transfer sandwich, transfer at 100V for {transfer_time_min} min in cold room",
        "Stain with Ponceau S to verify transfer, rinse with water",
        "Block membrane with {blocking_agent} in TBST for 1h at RT",
    ],
)
WESTERN_BLOT_TRANSFER._instruction_template = (
    "Perform western blot SDS-PAGE and membrane transfer for proteins {protein_range_kda} kDa. "
    "Use {gel_percentage}% acrylamide gel, load {sample_ug} µg protein per lane. "
    "Transfer to {membrane_type} for {transfer_time_min} min. Block with {blocking_agent}."
)


AGAROSE_GEL = ProtocolTemplate(
    template_id="agarose_gel_electrophoresis",
    name="Agarose Gel Electrophoresis",
    category="analysis",
    description="Separate DNA or RNA fragments by size using agarose gel with ethidium bromide or SYBR Safe staining.",
    tags=["gel electrophoresis", "DNA", "RNA", "fragment analysis"],
    parameters=[
        TemplateParameter("gel_percentage", "Agarose percentage", 1.0, "%", 0.5, 4.0),
        TemplateParameter("n_samples", "Number of samples", 8, "", 1, 20),
        TemplateParameter("dna_volume_ul", "Sample volume per lane", 5, "µL", 2, 20),
        TemplateParameter("voltage_v", "Running voltage", 100, "V", 50, 150),
        TemplateParameter("run_time_min", "Run time", 30, "min", 15, 90),
        TemplateParameter("stain", "DNA stain", "SYBR Safe",
                          choices=["SYBR Safe", "Ethidium Bromide", "GelRed"],
                          param_type="choice"),
        TemplateParameter("fragment_range_bp", "Expected fragment range", "100-3000", "bp",
                          choices=["50-500", "100-3000", "500-10000"], param_type="choice"),
    ],
    reagents=[
        "Agarose (molecular biology grade)",
        "TAE or TBE running buffer",
        "DNA stain (SYBR Safe or EtBr)",
        "6× loading dye",
        "DNA ladder (appropriate range)",
    ],
    equipment=[
        "Gel casting system",
        "Electrophoresis tank",
        "Power supply",
        "UV transilluminator or gel doc system",
        "Microwave",
    ],
    estimated_time_min=60,
    difficulty="easy",
    safety_level="warning",
    references=["Sambrook & Russell, Molecular Cloning 3rd Ed."],
    hint_steps=[
        "Dissolve {gel_percentage}% agarose in TAE buffer by microwaving",
        "Add stain when cooled to ~60°C, pour into casting tray",
        "Allow gel to solidify 30 min at RT",
        "Mix {n_samples} samples with 6× loading dye, load {dna_volume_ul} µL per lane",
        "Load DNA ladder in first lane",
        "Run at {voltage_v}V for {run_time_min} minutes",
        "Image on UV transilluminator (SYBR: blue light; EtBr: 302 nm UV)",
    ],
)
AGAROSE_GEL._instruction_template = (
    "Run {gel_percentage}% agarose gel electrophoresis for {n_samples} DNA samples "
    "({fragment_range_bp} bp range). Load {dna_volume_ul} µL per lane. "
    "Run at {voltage_v}V for {run_time_min} min. Stain with {stain}."
)


MINIPREP = ProtocolTemplate(
    template_id="plasmid_miniprep",
    name="Plasmid DNA Miniprep",
    category="prep",
    description="Isolate plasmid DNA from E. coli using alkaline lysis followed by spin-column purification.",
    tags=["plasmid", "miniprep", "DNA extraction", "E. coli"],
    parameters=[
        TemplateParameter("culture_volume_ml", "Overnight culture volume", 1.5, "mL", 0.5, 5),
        TemplateParameter("n_samples", "Number of cultures", 8, "", 1, 24),
        TemplateParameter("elution_volume_ul", "Elution volume", 50, "µL", 30, 100),
        TemplateParameter("lysis_time_min", "Lysis incubation time", 5, "min", 2, 10),
    ],
    reagents=[
        "Buffer P1 (resuspension buffer + RNase A)",
        "Buffer P2 (lysis buffer — NaOH + SDS)",
        "Buffer N3 or P3 (neutralisation buffer)",
        "Buffer PB (binding buffer)",
        "Buffer PE (wash buffer — contains ethanol)",
        "Elution buffer or nuclease-free water",
        "Spin columns with collection tubes",
    ],
    equipment=[
        "Microcentrifuge (≥13,000 rpm)",
        "Spin columns (e.g. Qiagen QIAprep)",
        "Vortex mixer",
        "Ice bucket",
        "Nanodrop or spectrophotometer",
    ],
    estimated_time_min=45,
    difficulty="easy",
    safety_level="safe",
    references=["Birnboim & Doly (1979) Nucleic Acids Res. 7:1513-1523"],
    hint_steps=[
        "Pellet {culture_volume_ml} mL overnight culture at 8000 rpm, 3 min",
        "Resuspend pellet in 250 µL Buffer P1 (ensure RNase A added)",
        "Add 250 µL Buffer P2, invert 4-6 times, incubate {lysis_time_min} min",
        "Add 350 µL Buffer N3, invert immediately until precipitate forms",
        "Centrifuge 10,000 rpm for 10 min",
        "Transfer supernatant to spin column, centrifuge 1 min",
        "Wash with 750 µL Buffer PE, centrifuge 1 min",
        "Discard flow-through, centrifuge 1 min to dry membrane",
        "Elute with {elution_volume_ul} µL elution buffer, centrifuge 1 min",
        "Measure DNA concentration on Nanodrop (A260/A280 ratio should be 1.8-2.0)",
    ],
)
MINIPREP._instruction_template = (
    "Perform plasmid DNA miniprep on {n_samples} E. coli cultures "
    "({culture_volume_ml} mL each) using spin-column purification. "
    "Elute with {elution_volume_ul} µL elution buffer. Quantify on Nanodrop."
)


# ---------------------------------------------------------------------------
# Template registry
# ---------------------------------------------------------------------------

TEMPLATE_REGISTRY: dict[str, ProtocolTemplate] = {
    t.template_id: t for t in [
        BCA_ASSAY,
        BRADFORD_ASSAY,
        ELISA_SANDWICH,
        MTT_ASSAY,
        PCR_STANDARD,
        WESTERN_BLOT_TRANSFER,
        AGAROSE_GEL,
        MINIPREP,
    ]
}


def get_template(template_id: str) -> ProtocolTemplate | None:
    return TEMPLATE_REGISTRY.get(template_id)


def list_templates(category: str | None = None) -> list[dict]:
    templates = list(TEMPLATE_REGISTRY.values())
    if category:
        templates = [t for t in templates if t.category == category]
    return [t.to_dict() for t in templates]


def build_instruction_from_template(template_id: str, params: dict) -> str | None:
    t = get_template(template_id)
    if not t:
        return None
    return t.build_instruction(params)