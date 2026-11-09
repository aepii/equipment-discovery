"""The part of the knowledge graph behind one annotated answer, as a Graphviz DOT string.

Reads left to right: question -> property asked about -> technique -> instrument (with contact), plus the
steps that must or may come first, the accessories to confirm and the suitable techniques that are not
in the dataset. Everything comes from the knowledge files and the checked answer; nothing is new here.
"""

import textwrap

import knowledge

# Fills light enough for dark text in both themes; the border carries the state. Every state also has
# a text label in the node, so color is never the only signal.
FIT_STYLE = {"high": ("#e3f4ec", "#1baf7a"), "medium": ("#fdebe1", "#eb6834"), "low": ("#efefec", "#898781")}
DEAD_END = ("#fbe4e4", "#d03b3b")
NEUTRAL = ("#e6effa", "#2a78d6")
EDGE = "#898781"
WRAP = 30  # characters per label line


def _wrap(text: str) -> str:
    """Break long label lines so nodes stay narrow."""
    return "\n".join(textwrap.fill(line, WRAP) for line in str(text).split("\n"))


def _quote(text: str) -> str:
    return '"' + str(text).replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n") + '"'


def _attrs(**attrs) -> str:
    return "[" + ", ".join(f"{key}={_quote(value)}" for key, value in attrs.items()) + "]"


KINDS = {"q": "question", "p": "property", "t": "technique", "i": "instrument", "a": "accessories"}


class _Graph:
    """Collects nodes and edges once, then writes them as DOT (Streamlit) or as plain data (web app)."""

    def __init__(self):
        self.nodes: dict[str, str] = {}
        self.edges: list[str] = []
        self.node_data: dict[str, dict] = {}
        self.edge_data: list[dict] = []

    def node(self, node_id: str, label: str, fill_border=NEUTRAL, **attrs) -> None:
        if node_id not in self.nodes:
            fill, border = fill_border
            self.nodes[node_id] = f"{_quote(node_id)} {_attrs(label=_wrap(label), fillcolor=fill, color=border, **attrs)}"
            kind = "missing" if fill_border == DEAD_END else KINDS.get(node_id.split(":")[0], "other")
            self.node_data[node_id] = {"id": node_id, "label": str(label), "kind": kind, "fill": fill,
                                       "border": border, "dashed": "dashed" in attrs.get("style", "")}

    def edge(self, a: str, b: str, label: str = "", **attrs) -> None:
        line = f"{_quote(a)} -> {_quote(b)} {_attrs(label=label, **attrs)}"
        if line not in self.edges:
            self.edges.append(line)
            self.edge_data.append({"source": a, "target": b, "label": label, "style": attrs.get("style", "solid")})

    def dot(self) -> str:
        head = ['digraph answer {', 'rankdir=LR; bgcolor="transparent"; nodesep=0.25; ranksep=0.5;',
                'node [shape=box, style="rounded,filled", fontname="Arial", fontsize=11, '
                'fontcolor="#0b0b0b", penwidth=1.5];',
                f'edge [color="{EDGE}", fontcolor="{EDGE}", fontname="Arial", fontsize=9];']
        return "\n".join(head + list(self.nodes.values()) + self.edges + ["}"])


def _technique(g: _Graph, tid: str, origin: str) -> str:
    """Add a technique node linked from the property (or the question) it answers; return its node ID."""
    node = f"t:{tid}"
    if tid in knowledge.techniques():
        g.node(node, knowledge.technique_name(tid), ("#ffffff", "#52514e"))
    else:
        g.node(node, f"{tid}\n(unknown technique)", ("#ffffff", "#898781"), style="rounded,filled,dashed")
    if origin:
        tech = knowledge.techniques().get(tid, {})
        partial = origin.startswith("p:") and origin[2:] in tech.get("partial", {})
        label = ("partly measured by" if partial else "measured by"
                 if tech.get("kind") in knowledge.MEASURING_KINDS else "uses")  # preparation, fabrication
        g.edge(origin, node, label, **({"style": "dashed"} if partial else {}))
    return node


GRAPH_ADDED = ("#f3eefb", "#7a5bd0")  # instruments added by graph matching, not chosen by the model


def _instrument_label(rec: dict) -> str:
    role = ("Also capable (added by graph)" if rec.get("source") == "graph"
            else "Can perform this" if rec.get("role", "primary") == "primary" else "Complementary only")
    state = "DEAD END" if rec.get("dead_end") else f"{rec['fit']} fit" if rec.get("fit") else ""
    return f"{rec['instrument']} ({rec['id']})\n{rec['contact']}\n{role}" + (f" · {state}" if state else "")


def _steps_before(g: _Graph, tid: str, node: str) -> None:
    """Prerequisite steps: where they can be done, or that they are missing."""
    for step in knowledge.workflow_for(tid)["requires"]:
        step_node = f"t:{step['technique']}"
        if step["status"] == "missing":
            g.node(step_node, f"{step['name']}\nNOT IN DATASET", DEAD_END, style="rounded,filled,dashed")
        else:
            where = "bench step" if step["status"] == "bench_step" else ", ".join(step["instruments"][:2])
            g.node(step_node, f"{step['name']}\n{where}", ("#ffffff", "#898781"))
        g.edge(step_node, node, "may come first" if step["conditional"] else "must come first", style="dotted")


def _follow_ups(g: _Graph, tid: str, node: str) -> None:
    """What a preparation or fabrication step is for, shown only when it is missing (the dead-end cause)."""
    for step in knowledge.workflow_for(tid)["leads_to"]:
        if step["status"] == "missing":
            g.node(f"t:{step['technique']}", f"{step['name']}\nNOT IN DATASET", DEAD_END,
                   style="rounded,filled,dashed")
            g.edge(node, f"t:{step['technique']}", "leads to", style="dotted")


def build_dot(result: dict) -> str:
    """DOT for one annotated result (empty if it has nothing to show)."""
    g = _build(result)
    return g.dot() if g else ""


def build_graph(result: dict) -> dict | None:
    """The same graph as plain data, {"nodes": [...], "edges": [...]}, for the web app (None if empty)."""
    g = _build(result)
    return {"nodes": list(g.node_data.values()), "edges": g.edge_data} if g else None


def _build(result: dict) -> _Graph | None:
    if result.get("mode") != "annotated" or result.get("error") or not (
            result.get("recommendations") or result.get("not_available")):
        return None
    g = _Graph()
    g.node("q", "Your question", ("#2a78d6", "#2a78d6"), fontcolor="#ffffff", shape="ellipse")
    for rec in result["recommendations"]:
        prop = rec.get("property_id", "")
        origin = "q"
        if prop:
            origin = f"p:{prop}"
            g.node(origin, knowledge.property_label(prop), ("#ffffff", "#2a78d6"), shape="ellipse")
            g.edge("q", origin, "asks about")
        tid = rec.get("technique_id", "")
        tech = _technique(g, tid, origin) if tid else origin
        if tid:
            _steps_before(g, tid, tech)
            _follow_ups(g, tid, tech)
        added = rec.get("source") == "graph"
        style = DEAD_END if rec.get("dead_end") else GRAPH_ADDED if added else FIT_STYLE.get(rec.get("fit"), NEUTRAL)
        inst = f"i:{rec['id']}"
        g.node(inst, _instrument_label(rec), style,
               **({} if rec.get("role", "primary") == "primary" else {"style": "rounded,filled,dashed"}))
        g.edge(tech, inst, "added by graph" if added else "performed on", **({"style": "dashed"} if added else {}))
        installed = knowledge.installed_for(rec["id"], tid) if tid else []
        items = ([f"Installed: {'; '.join(installed)}"] if installed else []) + (
            ["Confirm with contact:"] + [f"- {a}" for a in rec["accessories_to_confirm"]]
            if rec.get("accessories_to_confirm") else [])
        if items:
            g.node(f"a:{rec['id']}", "\n".join(items), ("#ffffff", "#c3c2b7"), shape="note")
            g.edge(inst, f"a:{rec['id']}", "accessories", arrowhead="none")
    asked = [n[2:] for n in g.nodes if n.startswith("p:")]
    for item in result.get("not_available", []):
        tid = str(item.get("technique_id") or "").strip()
        node = f"t:{tid or item.get('technique', '')}"
        if item.get("available_on"):  # wrongly called unavailable; the answer's own card already says so
            continue
        g.node(node, f"{item.get('technique') or knowledge.technique_name(tid)}\nNOT IN DATASET", DEAD_END,
               style="rounded,filled,dashed")
        tech = knowledge.techniques().get(tid, {})
        props = [p for p in asked if p in tech.get("measures", []) or p in tech.get("partial", {})]
        for origin in [f"p:{p}" for p in props] or ["q"]:
            g.edge(origin, node, "would be measured by", style="dashed")
    return g
