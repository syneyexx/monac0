from __future__ import annotations

import json
import math
import re
import sqlite3
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any

from .market_seed import ensure_markets_knowledge
from .general_knowledge_seed import ensure_general_business_knowledge


STOPWORDS = {
    "the", "and", "for", "with", "that", "this", "from", "into", "over", "under", "about", "after",
    "before", "your", "you", "are", "was", "were", "have", "has", "had", "can", "could", "should",
    "een", "het", "de", "dat", "dit", "die", "wat", "waar", "voor", "naar", "met", "van", "als", "dan",
    "maar", "ook", "zijn", "haar", "jouw", "mijn", "alles", "elke", "expert", "niveau", "leren",
}


@dataclass(slots=True)
class BrainNode:
    id: str
    label: str
    kind: str
    score: float = 1.0
    preview: str = ""
    source_count: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class BrainEdge:
    source: str
    target: str
    label: str = "relates"
    weight: float = 1.0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class BrainGraph:
    nodes: list[BrainNode]
    edges: list[BrainEdge]
    stats: dict[str, int | str]
    seeded: bool = False


def _slug(label: str, kind: str = "node") -> str:
    base = re.sub(r"[^a-zA-Z0-9]+", "_", (label or kind).strip().lower()).strip("_")[:80]
    return f"{kind}:{base or 'item'}"


def _clean_label(text: str, max_len: int = 48) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    if len(text) <= max_len:
        return text
    return text[: max_len - 1].rstrip() + "…"


def _extract_keywords(text: str, limit: int = 10) -> list[str]:
    words = re.findall(r"[A-Za-zÀ-ÿ0-9][A-Za-zÀ-ÿ0-9\-]{2,}", text or "")
    cleaned: list[str] = []
    for w in words:
        wl = w.lower().strip("-_")
        if len(wl) < 3 or wl in STOPWORDS or wl.isdigit():
            continue
        cleaned.append(wl)
    counts = Counter(cleaned)
    return [w.title() if len(w) <= 4 else w.replace("-", " ").title() for w, _ in counts.most_common(limit)]


def _parse_keywords(raw: str | None, fallback_text: str = "") -> list[str]:
    if raw:
        try:
            data = json.loads(raw)
            if isinstance(data, list):
                kws = [_clean_label(str(x), 36) for x in data if str(x).strip()]
                if kws:
                    return kws[:12]
        except Exception:
            pass
    return _extract_keywords(fallback_text, limit=8)


FOOTBALL_EXPERT_CHUNKS: list[dict[str, Any]] = [
    {
        "title": "Football tactical foundations",
        "topic": "Football",
        "keywords": ["tactics", "formations", "pressing", "positional play", "transitions"],
        "summary": "Core football tactics: formations, space, pressing, rest-defence and transitions.",
        "content": """
Football is best understood as a network of space, time, roles and decisions. A team shape is not just a formation on paper; it is an attacking structure, a defensive structure and a transition structure. Modern elite teams plan possession, counter-pressing, rest-defence and chance creation as one connected system. Formations such as 4-3-3, 4-2-3-1, 3-2-5 and 4-4-2 are starting references, but the real expert view is how players occupy lanes, create overloads, protect central zones and control the opponent after losing the ball.
""".strip(),
    },
    {
        "title": "Pressing and counter-pressing",
        "topic": "Football Tactics",
        "keywords": ["pressing traps", "gegenpressing", "counter-pressing", "defensive block"],
        "summary": "How teams win the ball through pressure, traps and compactness.",
        "content": """
Pressing is coordinated pressure on the ball, passing lanes and likely receiving zones. Elite pressing uses triggers such as a bad touch, a backward pass, a pass into a full-back, or a receiver facing their own goal. Counter-pressing tries to win the ball immediately after losing it, when the opponent is still disorganised. A team that cannot counter-press must protect itself with rest-defence: usually two or three players behind the attack positioned to stop counters.
""".strip(),
    },
    {
        "title": "Build-up play and positional play",
        "topic": "Football Tactics",
        "keywords": ["build-up", "positional play", "third man", "overload", "half-space"],
        "summary": "How teams progress from defence to attack using structure and spacing.",
        "content": """
Build-up play is the controlled progression of the ball from goalkeeper and defenders into midfield and attack. Positional play creates triangles, diamonds and free men by occupying five vertical lanes: left wing, left half-space, centre, right half-space and right wing. Third-man combinations are vital: player A passes to B, B lays off or connects to C, and C can face forward. The goal is not passing for style, but moving opponents until a lane or free player appears.
""".strip(),
    },
    {
        "title": "Football roles and player profiles",
        "topic": "Football Players",
        "keywords": ["goalkeeper", "centre-back", "full-back", "six", "eight", "ten", "winger", "striker"],
        "summary": "Key roles and how modern football profiles players.",
        "content": """
Modern player roles are more specific than classic positions. A goalkeeper may be a sweeper-keeper, a centre-back may be a ball-playing defender, a full-back may invert into midfield, a defensive midfielder may be a single pivot, an eight may be a box-to-box runner or interior, a ten may connect lines, a winger may hold width or attack inside, and a striker may be a target player, pressing forward or false nine. Scouting looks at role fit, not only raw talent.
""".strip(),
    },
    {
        "title": "Major football competitions",
        "topic": "Football Competitions",
        "keywords": ["FIFA World Cup", "UEFA Champions League", "Premier League", "La Liga", "Serie A", "Bundesliga", "Eredivisie"],
        "summary": "Major club and international football competitions.",
        "content": """
The largest international competition is the FIFA World Cup. European club football is anchored by the UEFA Champions League, Europa League and Conference League. Domestic leagues create the weekly elite football ecosystem: Premier League in England, La Liga in Spain, Serie A in Italy, Bundesliga in Germany, Ligue 1 in France and Eredivisie in the Netherlands. Cup tournaments add knockout volatility, while leagues reward consistency across a season.
""".strip(),
    },
    {
        "title": "Dutch football identity",
        "topic": "Dutch Football",
        "keywords": ["Total Football", "Ajax", "Feyenoord", "PSV", "Eredivisie", "Johan Cruyff"],
        "summary": "Dutch football ideas: Total Football, youth development and positional intelligence.",
        "content": """
Dutch football is historically connected to Total Football, positional intelligence, technical training and youth development. Ajax, Feyenoord and PSV form the traditional top of Dutch club football, while the Eredivisie is known for developing young technical players. Johan Cruyff influenced both Dutch football and Barcelona's identity by connecting technique, spacing, decision-making and bravery on the ball.
""".strip(),
    },
    {
        "title": "Football analytics and data",
        "topic": "Football Analytics",
        "keywords": ["expected goals", "xG", "pressures", "progressive passes", "shot quality", "packing"],
        "summary": "Important football analytics metrics and why they matter.",
        "content": """
Football analytics turns match events into signals. Expected goals estimates shot quality. Progressive passes and carries measure ball progression. Pressures and counter-pressing recoveries show defensive activity. Field tilt shows territory. Shot creation and expected threat help estimate how teams create danger before the final shot. Expert use of data combines numbers with video, because context explains why the numbers happened.
""".strip(),
    },
    {
        "title": "Training methodology",
        "topic": "Football Coaching",
        "keywords": ["training", "periodisation", "small-sided games", "match model", "coaching"],
        "summary": "How coaches connect training sessions to a match model.",
        "content": """
Expert football coaching starts with a match model: how the team wants to attack, defend and transition. Training then uses small-sided games, constraints and repetition to create habits. Tactical periodisation connects physical work to football actions instead of separating running from the game. The best sessions contain decision-making, intensity, communication and realistic pressure.
""".strip(),
    },
    {
        "title": "Scouting and recruitment",
        "topic": "Football Scouting",
        "keywords": ["scouting", "recruitment", "role fit", "potential", "video analysis"],
        "summary": "How clubs identify players by role, data, video and development potential.",
        "content": """
Scouting is not simply finding good players; it is finding players who fit a club's role, budget, age profile and tactical needs. Recruitment departments combine live scouting, video, data filters and background research. A winger for a possession team may need different qualities than a winger for a counter-attacking team. Potential is judged by physical tools, technical level, tactical learning speed and mentality.
""".strip(),
    },
    {
        "title": "Match analysis workflow",
        "topic": "Football Analysis",
        "keywords": ["match analysis", "video", "phases", "opponent analysis", "set pieces"],
        "summary": "How analysts break down matches into phases and actionable insights.",
        "content": """
A strong match analysis workflow separates the game into phases: own build-up, attacking progression, chance creation, defensive organisation, pressing, transition to attack, transition to defence and set pieces. Analysts look for repeated patterns rather than isolated moments. The output should be actionable: where to press, where space appears, which player receives under pressure, and which set-piece weaknesses can be targeted.
""".strip(),
    },
    {
        "title": "Set pieces",
        "topic": "Football Tactics",
        "keywords": ["corners", "free kicks", "throw-ins", "set pieces", "routines"],
        "summary": "Set-piece strategy: routines, blockers, zones and second balls.",
        "content": """
Set pieces are high-value moments because the ball is static and structure can be planned. Corners may use blockers, screens, near-post runs, far-post isolation or cut-backs to the edge of the box. Defensive set pieces can be zonal, man-marking or hybrid. Throw-ins are also tactical moments: good teams use them to escape pressure or create territorial advantage.
""".strip(),
    },
    {
        "title": "Football mental side",
        "topic": "Football Psychology",
        "keywords": ["mentality", "confidence", "pressure", "leadership", "team culture"],
        "summary": "Mental and cultural factors that influence football performance.",
        "content": """
Football performance is strongly affected by confidence, pressure handling, leadership and team culture. Elite teams create clarity so players know what to do under stress. Captains and senior players shape standards. Mental resilience is visible after mistakes, conceded goals and difficult away matches. Good tactical plans still fail when communication and belief collapse.
""".strip(),
    },
]


GENERAL_EXPERT_CHUNKS: list[dict[str, Any]] = [
    {
        "title": "Artificial intelligence foundations",
        "topic": "Artificial Intelligence",
        "keywords": ["machine learning", "neural networks", "reasoning", "agents", "data", "models"],
        "summary": "AI studies systems that perceive, learn, reason, generate and act.",
        "content": """
Artificial intelligence is the field of building systems that can perform tasks normally associated with human intelligence: perception, language, reasoning, planning, prediction and action. Modern AI often combines machine learning, neural networks, search, retrieval, memory and tool use. A strong AI assistant is not only a model; it is a system containing data pipelines, memory, safety checks, retrieval, interfaces, logs, evaluation and feedback loops.
""".strip(),
    },
    {
        "title": "Local AI architecture",
        "topic": "Artificial Intelligence",
        "keywords": ["local AI", "LLM", "SQLite", "retrieval", "RAG", "privacy"],
        "summary": "A local AI stack stores knowledge privately and routes questions through retrieval plus an LLM.",
        "content": """
A private local AI bot usually contains a local language model, a database, a retrieval system and user interfaces such as desktop GUI or Telegram. SQLite can store conversations, memory facts, documents, web pages, errors and learning jobs. Retrieval augmented generation (RAG) searches the local knowledge before answering, so the bot can use learned information instead of only relying on model weights. Good architecture separates UI, command routing, memory, web research, LLM calls and database code.
""".strip(),
    },
    {
        "title": "Databases and knowledge storage",
        "topic": "Databases",
        "keywords": ["SQLite", "tables", "indexes", "FTS", "schema", "transactions"],
        "summary": "Databases make an AI brain searchable, durable and structured.",
        "content": """
A database turns loose text into durable structured knowledge. Tables store entities such as conversations, memory facts, sources and knowledge chunks. Indexes make lookup faster. Full-text search helps find relevant text by words and phrases. Transactions keep writes safe. A knowledge database becomes more valuable when it records source, date, topic, confidence, summary, keywords and relationships between concepts.
""".strip(),
    },
    {
        "title": "Cybersecurity basics",
        "topic": "Cybersecurity",
        "keywords": ["threats", "authentication", "encryption", "least privilege", "logging", "backups"],
        "summary": "Security protects systems through identity, permissions, monitoring and recovery.",
        "content": """
Cybersecurity protects confidentiality, integrity and availability. Core practices include strong authentication, least privilege, patching, secure backups, encryption, network segmentation, logging and incident response. For a private AI project, important risks include leaking API keys, exposing local services to the internet, trusting unverified downloaded files, and letting an agent execute actions without approval.
""".strip(),
    },
    {
        "title": "Programming fundamentals",
        "topic": "Programming",
        "keywords": ["Python", "functions", "modules", "errors", "testing", "architecture"],
        "summary": "Programming turns ideas into reliable instructions through structure and testing.",
        "content": """
Programming is the practice of designing instructions that computers can execute. Expert code is not only code that works once; it is readable, testable, maintainable and safe under errors. Important concepts include variables, functions, modules, data structures, error handling, logging, tests, interfaces and separation of concerns. Python is popular for AI because it has strong libraries and simple syntax.
""".strip(),
    },
    {
        "title": "Mathematics for reasoning",
        "topic": "Mathematics",
        "keywords": ["algebra", "probability", "statistics", "logic", "linear algebra", "optimization"],
        "summary": "Math gives language for patterns, uncertainty, structure and proof.",
        "content": """
Mathematics provides precise tools for reasoning. Algebra describes relationships. Probability models uncertainty. Statistics turns data into evidence. Logic studies valid reasoning. Linear algebra represents vectors, matrices and transformations, which are central to machine learning. Optimization searches for best solutions under constraints. A good AI brain benefits from storing formulas, definitions, examples and edge cases.
""".strip(),
    },
    {
        "title": "Physics overview",
        "topic": "Physics",
        "keywords": ["energy", "motion", "forces", "waves", "electricity", "thermodynamics"],
        "summary": "Physics studies matter, energy, forces, fields and change.",
        "content": """
Physics explains how the physical world behaves. Classical mechanics studies motion and forces. Thermodynamics studies heat, energy and entropy. Electromagnetism studies electric and magnetic fields. Waves describe oscillations such as sound, light and radio signals. Quantum mechanics studies matter and energy at small scales. Expert understanding connects equations to real examples and measurement limits.
""".strip(),
    },
    {
        "title": "Chemistry overview",
        "topic": "Chemistry",
        "keywords": ["atoms", "molecules", "bonds", "reactions", "acids", "organic chemistry"],
        "summary": "Chemistry studies substances, bonds, reactions and material properties.",
        "content": """
Chemistry studies matter at the level of atoms, molecules and reactions. Atomic structure influences bonding. Chemical bonds determine properties. Reactions rearrange atoms while conserving mass. Acids and bases exchange protons or electrons depending on the model. Organic chemistry studies carbon-based compounds. Safety matters because concentration, temperature, pressure and mixing order can change risk.
""".strip(),
    },
    {
        "title": "Biology and life systems",
        "topic": "Biology",
        "keywords": ["cells", "DNA", "evolution", "ecosystems", "homeostasis", "organisms"],
        "summary": "Biology studies living systems from molecules to ecosystems.",
        "content": """
Biology studies life. Cells are the basic units of living organisms. DNA stores hereditary information. Proteins perform many cellular functions. Evolution explains how populations change over generations through variation, inheritance and selection. Ecosystems describe interactions between organisms and environments. Homeostasis is the regulation that keeps internal conditions stable.
""".strip(),
    },
    {
        "title": "Finance basics",
        "topic": "Finance",
        "keywords": ["cash flow", "budget", "risk", "return", "compound interest", "liquidity"],
        "summary": "Finance manages money, risk, time and decisions under uncertainty.",
        "content": """
Finance studies how people and organizations allocate money over time. Key ideas include cash flow, budgeting, risk, return, liquidity, debt, interest and diversification. Compound interest means returns can grow on previous returns. A healthy financial decision considers downside risk, time horizon, cash needs and uncertainty. For business, cash flow can matter more than profit on paper.
""".strip(),
    },
    {
        "title": "Business operations",
        "topic": "Business",
        "keywords": ["customers", "processes", "suppliers", "value", "sales", "quality"],
        "summary": "Business creates value through products, customers, operations and relationships.",
        "content": """
Business operations connect customer demand, suppliers, people, processes, quality and money. A company creates value when it solves a problem for customers better than alternatives. Important operational concepts include procurement, inventory, order handling, customer service, invoices, margins, delivery reliability and process improvement. Strong documentation makes work repeatable and less dependent on memory.
""".strip(),
    },
    {
        "title": "History thinking",
        "topic": "History",
        "keywords": ["chronology", "sources", "causation", "context", "continuity", "change"],
        "summary": "History explains change over time using sources, context and causation.",
        "content": """
History is not just dates; it is interpretation of change over time. Expert historical thinking asks who created a source, why it was created, what context shaped it, and what other evidence supports or contradicts it. Important concepts include chronology, causation, continuity, change, perspective, power and unintended consequences.
""".strip(),
    },
    {
        "title": "Geography and world systems",
        "topic": "Geography",
        "keywords": ["place", "climate", "population", "trade", "resources", "maps"],
        "summary": "Geography studies places, environments, movement and human systems.",
        "content": """
Geography studies the relationship between people, places and environments. Physical geography includes landforms, climate, water and ecosystems. Human geography includes population, cities, migration, culture, trade and political boundaries. Maps are models, not perfect reality: projection, scale and selected data shape what people see.
""".strip(),
    },
    {
        "title": "Psychology basics",
        "topic": "Psychology",
        "keywords": ["attention", "memory", "motivation", "emotion", "bias", "learning"],
        "summary": "Psychology studies behaviour and mental processes.",
        "content": """
Psychology studies behaviour, thought, emotion and learning. Attention is limited, memory is reconstructive, motivation is shaped by goals and rewards, and decisions are influenced by biases. Expert use of psychology avoids overclaiming from pop theories and looks for evidence, context and individual differences.
""".strip(),
    },
    {
        "title": "Medical knowledge safety",
        "topic": "Medicine",
        "keywords": ["symptoms", "diagnosis", "risk", "evidence", "emergency", "doctor"],
        "summary": "Medical knowledge must be evidence-based and careful because mistakes can harm people.",
        "content": """
Medical knowledge covers symptoms, causes, diagnosis, treatment and prevention. Safe medical reasoning separates general information from personal diagnosis. Red flags such as severe chest pain, breathing difficulty, stroke symptoms, severe allergic reaction or uncontrolled bleeding require urgent professional help. An AI can explain concepts and suggest questions, but it should not replace a qualified clinician.
""".strip(),
    },
]

GENERAL_FACTS = [
    ("M0N4C0 Brain", "contains", "Artificial Intelligence"),
    ("M0N4C0 Brain", "contains", "Databases"),
    ("M0N4C0 Brain", "contains", "Cybersecurity"),
    ("M0N4C0 Brain", "contains", "Programming"),
    ("M0N4C0 Brain", "contains", "Mathematics"),
    ("M0N4C0 Brain", "contains", "Physics"),
    ("M0N4C0 Brain", "contains", "Chemistry"),
    ("M0N4C0 Brain", "contains", "Biology"),
    ("M0N4C0 Brain", "contains", "Finance"),
    ("M0N4C0 Brain", "contains", "Business"),
    ("M0N4C0 Brain", "contains", "History"),
    ("M0N4C0 Brain", "contains", "Geography"),
    ("M0N4C0 Brain", "contains", "Psychology"),
    ("M0N4C0 Brain", "contains", "Medicine"),
    ("Artificial Intelligence", "uses", "Databases"),
    ("Artificial Intelligence", "uses", "Programming"),
    ("Artificial Intelligence", "uses", "Mathematics"),
    ("Local AI", "protects", "Privacy"),
    ("Databases", "support", "Knowledge Graphs"),
    ("Cybersecurity", "protects", "Private AI"),
    ("Finance", "uses", "Mathematics"),
    ("Physics", "connects_to", "Chemistry"),
    ("Chemistry", "connects_to", "Biology"),
    ("Psychology", "connects_to", "Learning"),
]


FOOTBALL_FACTS = [
    ("Football", "contains", "Tactics"),
    ("Football", "contains", "Players"),
    ("Football", "contains", "Competitions"),
    ("Football", "contains", "Analytics"),
    ("Football Tactics", "uses", "Pressing"),
    ("Football Tactics", "uses", "Positional Play"),
    ("Football Tactics", "uses", "Transitions"),
    ("Pressing", "creates", "Turnovers"),
    ("Counter-Pressing", "protects", "Rest-Defence"),
    ("Build-Up Play", "creates", "Free Man"),
    ("Positional Play", "uses", "Half-Spaces"),
    ("Football Analytics", "measures", "Expected Goals"),
    ("Football Analytics", "supports", "Scouting"),
    ("Dutch Football", "influenced_by", "Johan Cruyff"),
    ("Dutch Football", "features", "Ajax"),
    ("Dutch Football", "features", "Feyenoord"),
    ("Dutch Football", "features", "PSV"),
    ("Football Competitions", "includes", "FIFA World Cup"),
    ("Football Competitions", "includes", "UEFA Champions League"),
    ("Football Competitions", "includes", "Eredivisie"),
]


def ensure_general_foundation_knowledge(db: Any) -> bool:
    """Add the general foundation pack once, even when an older DB already has football seed data."""
    try:
        with db.connect() as conn:
            row = conn.execute(
                "SELECT id FROM knowledge_sources WHERE title=? LIMIT 1",
                ("M0N4C0 Seed Knowledge: General Foundation Brain Pack",),
            ).fetchone()
            if row:
                return False
    except Exception:
        return False
    general_source_id = db.add_source(
        "seed",
        "M0N4C0 Seed Knowledge: General Foundation Brain Pack",
        None,
        "General Knowledge",
        metadata={"created_for": "Brain Nodes base knowledge", "level": "expert", "offline_seed": True},
        reliability=0.80,
    )
    for idx, item in enumerate(GENERAL_EXPERT_CHUNKS):
        db.add_chunk(
            source_id=general_source_id,
            topic=item["topic"],
            title=item["title"],
            url=None,
            chunk_index=idx,
            content=item["content"],
            summary=item["summary"],
            keywords=item["keywords"],
            quality_score=0.82,
        )
    for subject, predicate, obj in GENERAL_FACTS:
        db.add_memory_fact(subject, predicate, obj, source="general_seed", confidence=0.84)
    return True

def seed_default_football_knowledge(db: Any) -> bool:
    """Fill an empty local brain with expert football + broad foundational knowledge.

    This is intentionally local/offline seed data. It gives the Brain Nodes view
    something useful to render before the user has learned/imported anything.
    """
    stats = db.stats()
    if int(stats.get("knowledge_chunks", 0)) > 0 or int(stats.get("memory_facts", 0)) > 0:
        return False

    football_source_id = db.add_source(
        "seed",
        "M0N4C0 Seed Knowledge: Expert Football Brain Pack",
        None,
        "Football",
        metadata={"created_for": "Brain Nodes demo", "level": "expert", "offline_seed": True},
        reliability=0.82,
    )
    general_source_id = db.add_source(
        "seed",
        "M0N4C0 Seed Knowledge: General Foundation Brain Pack",
        None,
        "General Knowledge",
        metadata={"created_for": "Brain Nodes base knowledge", "level": "expert", "offline_seed": True},
        reliability=0.80,
    )

    for idx, item in enumerate(FOOTBALL_EXPERT_CHUNKS):
        db.add_chunk(
            source_id=football_source_id,
            topic=item["topic"],
            title=item["title"],
            url=None,
            chunk_index=idx,
            content=item["content"],
            summary=item["summary"],
            keywords=item["keywords"],
            quality_score=0.86,
        )
    for idx, item in enumerate(GENERAL_EXPERT_CHUNKS):
        db.add_chunk(
            source_id=general_source_id,
            topic=item["topic"],
            title=item["title"],
            url=None,
            chunk_index=idx,
            content=item["content"],
            summary=item["summary"],
            keywords=item["keywords"],
            quality_score=0.82,
        )
    for subject, predicate, obj in FOOTBALL_FACTS + GENERAL_FACTS:
        db.add_memory_fact(subject, predicate, obj, source="brain_seed", confidence=0.86)
    return True

class BrainGraphBuilder:
    def __init__(self, db: Any):
        self.db = db

    def build(
        self,
        query: str = "",
        limit: int = 130,
        include_seed_if_empty: bool = True,
        max_nodes: int | None = None,
    ) -> BrainGraph:
        """Build an in-memory graph for the Brain Nodes view.

        Older/newer GUI builds used two names for the same concept:
        ``limit`` and ``max_nodes``. Accept both so Brain Nodes keeps working
        across patched GUI/service versions instead of crashing with:
        ``TypeError: build() got an unexpected keyword argument 'max_nodes'``.
        """
        if max_nodes is not None:
            try:
                limit = int(max_nodes)
            except (TypeError, ValueError):
                limit = 130
        limit = max(25, min(int(limit or 130), 1000))
        seeded = False
        if include_seed_if_empty:
            seeded = seed_default_football_knowledge(self.db)
            # Older zip/database may already contain football seed but not the broad base pack.
            seeded = ensure_general_foundation_knowledge(self.db) or seeded
            # Always preserve existing data, but add the expert markets pack once.
            seeded = ensure_markets_knowledge(self.db) or seeded
            # Extra broad practical knowledge: business, money, taxes, operations.
            seeded = ensure_general_business_knowledge(self.db) or seeded

        nodes: dict[str, BrainNode] = {}
        edge_weights: dict[tuple[str, str, str], float] = defaultdict(float)
        edge_meta: dict[tuple[str, str, str], dict[str, Any]] = {}

        def add_node(label: str, kind: str, score: float = 1.0, preview: str = "", **metadata: Any) -> str:
            label_clean = _clean_label(label, 58)
            node_id = _slug(label_clean, kind)
            if node_id in nodes:
                n = nodes[node_id]
                n.score += score
                n.source_count += 1
                if preview and len(preview) > len(n.preview):
                    n.preview = _clean_label(preview, 260)
                n.metadata.update({k: v for k, v in metadata.items() if v is not None})
            else:
                nodes[node_id] = BrainNode(
                    id=node_id,
                    label=label_clean,
                    kind=kind,
                    score=score,
                    preview=_clean_label(preview, 260),
                    source_count=1,
                    metadata={k: v for k, v in metadata.items() if v is not None},
                )
            return node_id

        def add_edge(source: str, target: str, label: str = "relates", weight: float = 1.0, **metadata: Any) -> None:
            if not source or not target or source == target:
                return
            key = (source, target, label)
            edge_weights[key] += weight
            edge_meta.setdefault(key, {}).update({k: v for k, v in metadata.items() if v is not None})

        core_id = add_node("M0N4C0 Brain", "core", 7.5, "Local visual map of everything stored in SQLite: knowledge, memory facts and recent conversations.")
        q = (query or "").strip()

        with self.db.connect() as conn:
            conn.row_factory = sqlite3.Row
            if q:
                like = f"%{q}%"
                chunk_rows = conn.execute(
                    """
                    SELECT * FROM knowledge_chunks
                    WHERE coalesce(topic,'') LIKE ? OR coalesce(title,'') LIKE ? OR content LIKE ? OR coalesce(summary,'') LIKE ?
                    ORDER BY quality_score DESC, id DESC LIMIT ?
                    """,
                    (like, like, like, like, max(25, limit)),
                ).fetchall()
                fact_rows = conn.execute(
                    """
                    SELECT * FROM memory_facts
                    WHERE subject LIKE ? OR predicate LIKE ? OR object LIKE ?
                    ORDER BY confidence DESC, updated_at DESC LIMIT ?
                    """,
                    (like, like, like, max(25, limit)),
                ).fetchall()
                conversation_rows = conn.execute(
                    """
                    SELECT * FROM conversations
                    WHERE content LIKE ?
                    ORDER BY id DESC LIMIT 25
                    """,
                    (like,),
                ).fetchall()
            else:
                chunk_rows = conn.execute(
                    "SELECT * FROM knowledge_chunks ORDER BY quality_score DESC, id DESC LIMIT ?",
                    (max(70, limit),),
                ).fetchall()
                fact_rows = conn.execute(
                    "SELECT * FROM memory_facts ORDER BY confidence DESC, updated_at DESC LIMIT ?",
                    (max(70, limit),),
                ).fetchall()
                conversation_rows = conn.execute(
                    "SELECT * FROM conversations ORDER BY id DESC LIMIT 45"
                ).fetchall()

        for row in chunk_rows:
            topic = row["topic"] or "Knowledge"
            title = row["title"] or topic
            summary = row["summary"] or row["content"][:220]
            topic_id = add_node(topic, "topic", 2.2, f"Topic with local knowledge chunks. Example: {summary}")
            title_id = add_node(
                title,
                "chunk",
                1.4 + float(row["quality_score"] or 0.5),
                summary,
                chunk_id=row["id"],
                url=row["url"],
                topic=topic,
                title=title,
                created_at=row["created_at"],
            )
            add_edge(core_id, topic_id, "contains", 2.0)
            add_edge(topic_id, title_id, "chunk", 1.5, chunk_id=row["id"])
            keywords = _parse_keywords(row["keywords_json"], f"{title} {summary} {row['content'][:800]}")
            for kw in keywords[:8]:
                kw_kind = "keyword"
                kw_id = add_node(kw, kw_kind, 0.75, f"Keyword found inside: {title}")
                add_edge(title_id, kw_id, "mentions", 0.75)
                add_edge(topic_id, kw_id, "topic keyword", 0.45)

        for row in fact_rows:
            subject = str(row["subject"])
            predicate = str(row["predicate"])
            obj = str(row["object"])
            s_id = add_node(subject, "memory", 1.7, f"Memory fact: {subject} {predicate} {obj}")
            o_id = add_node(obj, "entity", 1.2, f"Linked by memory relation: {predicate}")
            add_edge(core_id, s_id, "remembers", 0.8)
            add_edge(s_id, o_id, predicate[:32] or "related", float(row["confidence"] or 0.75) + 0.5)

        if conversation_rows:
            conv_id = add_node("Recent Conversations", "conversation", 2.4, "Recent user/bot messages stored locally.")
            add_edge(core_id, conv_id, "history", 1.0)
            combined = "\n".join(str(r["content"]) for r in conversation_rows)
            for kw in _extract_keywords(combined, limit=18):
                kw_id = add_node(kw, "conversation_term", 0.6, "Term extracted from recent chat history.")
                add_edge(conv_id, kw_id, "recently discussed", 0.55)

        # Keep the graph usable. Prefer high-score nodes, but keep all core/topic nodes.
        if len(nodes) > limit:
            ordered = sorted(nodes.values(), key=lambda n: (n.kind in {"core", "topic"}, n.score), reverse=True)
            keep = {n.id for n in ordered[:limit]}
            nodes = {k: v for k, v in nodes.items() if k in keep}
        else:
            keep = set(nodes.keys())

        edges = [
            BrainEdge(source=s, target=t, label=l, weight=w, metadata=edge_meta.get((s, t, l), {}))
            for (s, t, l), w in edge_weights.items()
            if s in keep and t in keep
        ]
        edges.sort(key=lambda e: e.weight, reverse=True)
        edges = edges[: max(limit * 2, 80)]

        kind_counts = Counter(n.kind for n in nodes.values())
        stats: dict[str, int | str] = {
            "nodes": len(nodes),
            "edges": len(edges),
            "knowledge_chunks": len(chunk_rows),
            "memory_facts": len(fact_rows),
            "conversations": len(conversation_rows),
            "query": q or "all",
        }
        for kind, count in kind_counts.items():
            stats[f"kind_{kind}"] = count

        return BrainGraph(nodes=sorted(nodes.values(), key=lambda n: n.score, reverse=True), edges=edges, stats=stats, seeded=seeded)
