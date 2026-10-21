"""Offline exports and read-only MCP views over a Graphify JSON snapshot."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import deque
from pathlib import Path
from urllib.parse import quote

GENERATION_ID = re.compile(r"[0-9a-f]{32}\Z")


def runtime_path(path: Path) -> Path:
    """Resolve an input path only within a complete runtime generation graph."""
    runtime = Path.cwd().resolve()
    candidate = path.resolve()
    try:
        relative = candidate.relative_to(runtime)
    except ValueError as exc:
        raise ValueError("graph must be inside the current Graphify runtime") from exc
    if (
        len(relative.parts) != 4
        or relative.parts[0] != "generations"
        or not GENERATION_ID.fullmatch(relative.parts[1])
        or relative.parts[2:] != ("graphify-out", "graph.json")
    ):
        raise ValueError("graph must be a runtime generation graph.json")
    return candidate


def export_path(path: Path) -> Path:
    """Resolve an output only below exports and reject a symlink destination."""
    runtime = Path.cwd().resolve()
    exports = runtime / "exports"
    candidate = path.resolve()
    try:
        candidate.relative_to(exports)
    except ValueError as exc:
        raise ValueError("output must be inside the current runtime exports") from exc
    if path.is_symlink():
        raise ValueError("output must not be a symlink")
    return candidate


def load_graph(path: Path) -> dict:
    with path.open(encoding="utf-8-sig") as stream:
        graph = json.load(stream)
    if not isinstance(graph, dict) or not isinstance(graph.get("nodes", []), list):
        raise TypeError("graph must be a JSON object with a nodes list")
    edges = graph.get("links", graph.get("edges", []))
    if not isinstance(edges, list):
        raise TypeError("graph edges must be a list")
    for node in graph.get("nodes", []):
        if not isinstance(node, dict) or not isinstance(
            node.get("id", node.get("name", "")), (str, int)
        ):
            raise TypeError("graph nodes must be objects with string or integer ids")
    for edge in edges:
        if (
            not isinstance(edge, dict)
            or not isinstance(edge.get("source", edge.get("from", "")), (str, int))
            or not isinstance(edge.get("target", edge.get("to", "")), (str, int))
        ):
            raise TypeError(
                "graph edges must be objects with string or integer endpoints"
            )
    return graph


def nodes_edges(graph: dict) -> tuple[list[dict], list[dict]]:
    nodes = [n for n in graph.get("nodes", []) if isinstance(n, dict)]
    edges = [
        e for e in graph.get("links", graph.get("edges", [])) if isinstance(e, dict)
    ]
    return nodes, edges


def node_id(node: dict) -> str:
    return str(node.get("id", node.get("name", "")))


def edge_ends(edge: dict) -> tuple[str, str]:
    return str(edge.get("source", edge.get("from", ""))), str(
        edge.get("target", edge.get("to", ""))
    )


def node_label(node: dict) -> str:
    return str(node.get("name", node.get("label", node_id(node))))


def source_ref(node: dict) -> str:
    file = str(node.get("source_file", node.get("file_path", node.get("file", ""))))
    location = str(
        node.get("source_location", node.get("location", node.get("line", "")))
    )
    return f"{file}:{location}" if file and location else file or location or "unknown"


def safe_slug(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip(".-")[:80]
    return slug or "group"


def md_text(value: object) -> str:
    return re.sub(r"([\\`*_{}\[\]()#+.!|<>])", r"\\\1", str(value))


def md_code(value: object) -> str:
    text = str(value).replace("\r", " ").replace("\n", " ")
    delimiter = "`" * (
        max((len(match.group(0)) for match in re.finditer(r"`+", text)), default=0) + 1
    )
    padding = " " if text.startswith("`") or text.endswith("`") else ""
    return f"{delimiter}{padding}{text}{padding}{delimiter}"


def export_html(graph: dict, output: Path) -> None:
    output = export_path(output)
    nodes, edges = nodes_edges(graph)
    payload = (
        json.dumps({"nodes": nodes, "edges": edges}, ensure_ascii=True)
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
    )
    page = f"""<!doctype html>
<html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline';">
<title>Local code graph</title><style>
body{{font:15px system-ui,sans-serif;margin:2rem;max-width:1100px;color:#18212b}} input{{padding:.6rem;width:min(35rem,90%)}} li{{margin:.7rem 0}} code{{color:#394d63}} .edge{{color:#526476}} .tag{{border:1px solid #bbc7d2;border-radius:1rem;padding:.1rem .45rem;font-size:.8em}} a{{color:#0759a5}} #edges{{margin-top:2rem}}
</style><h1>Local code graph</h1><p>Offline snapshot. Search symbols and inspect their relationships and source references.</p>
<label>Search <input id="q" type="search" autocomplete="off"></label><p id="count"></p><ul id="results"></ul><section id="edges"><h2>Relationships</h2><ul id="relations"></ul></section>
<script>const graph={payload};const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}}[c]));const byId=new Map(graph.nodes.map(n=>[String(n.id??n.name??''),n]));const q=document.querySelector('#q');function draw(){{const term=q.value.toLowerCase();const ns=graph.nodes.filter(n=>JSON.stringify(n).toLowerCase().includes(term));document.querySelector('#count').textContent=ns.length+' symbols';document.querySelector('#results').innerHTML=ns.slice(0,300).map(n=>'<li><b>'+esc(n.name??n.label??n.id)+'</b> <span class="tag">'+esc(n.type??n.kind??'symbol')+'</span><br><code>'+esc(n.source_file??n.file_path??n.file??'')+':'+esc(n.source_location??n.location??n.line??'')+'</code></li>').join('');const ids=new Set(ns.map(n=>String(n.id??n.name??'')));const es=graph.edges.filter(e=>ids.has(String(e.source??e.from??''))||ids.has(String(e.target??e.to??'')));document.querySelector('#relations').innerHTML=es.slice(0,500).map(e=>{{const a=byId.get(String(e.source??e.from??'')),b=byId.get(String(e.target??e.to??''));return '<li class="edge">'+esc(a?.name??e.source??e.from)+'  ->  '+esc(b?.name??e.target??e.to)+' <span class="tag">'+esc(e.type??e.label??'relates')+'</span> <span class="tag">confidence '+esc(e.confidence??'unknown')+'</span></li>'}}).join('')}}q.addEventListener('input',draw);draw();</script></html>"""
    with output.open("w", encoding="utf-8") as stream:
        stream.write(page)


def wiki_groups(nodes: list[dict]) -> dict[str, list[dict]]:
    groups: dict[str, list[dict]] = {}
    for node in nodes:
        group = str(node.get("community", node.get("cluster", "")))
        if not group:
            group = source_ref(node).split(":", 1)[0] or "unmapped"
        groups.setdefault(group, []).append(node)
    return groups


def wiki_related(
    nodes: list[dict], edges: list[dict]
) -> dict[str, list[tuple[str, dict, dict]]]:
    by_id = {node_id(node): node for node in nodes}
    related: dict[str, list[tuple[str, dict, dict]]] = {}
    for edge in edges:
        src, dst = edge_ends(edge)
        if src in by_id and dst in by_id:
            related.setdefault(src, []).append(("depends on", by_id[dst], edge))
            if dst != src:
                related.setdefault(dst, []).append(
                    ("called by / referenced by", by_id[src], edge)
                )
    return related


def export_wiki(graph: dict, output: Path) -> None:
    output = export_path(output)
    nodes, edges = nodes_edges(graph)
    groups = wiki_groups(nodes)
    if output.exists() and any(output.iterdir()):
        raise ValueError("wiki output directory must be empty")
    output.mkdir(parents=True, exist_ok=True)
    related_by_id = wiki_related(nodes, edges)
    slugs = {
        group: f"{safe_slug(group)[:64]}-{hashlib.sha256(group.encode('utf-8')).hexdigest()[:12]}"
        for group in groups
    }
    lines = [
        "# Local code graph",
        "",
        "Generated from a local snapshot; no model or network access.",
        "",
        "## Groups",
        "",
    ]
    lines += [
        f"- [{md_text(group)}](groups/{quote(slugs[group], safe='._-')}.md)"
        for group in sorted(groups)
    ]
    with (output / "index.md").open("w", encoding="utf-8") as stream:
        stream.write("\n".join(lines) + "\n")
    directory = output / "groups"
    directory.mkdir(exist_ok=True)
    for group, members in sorted(groups.items()):
        body = [f"# {md_text(group)}", ""]
        for node in sorted(members, key=node_label):
            ident = node_id(node)
            body += [
                f"## {md_text(node_label(node))}",
                "",
                f"Source: {md_code(source_ref(node))}",
                "",
            ]
            related = related_by_id.get(ident, [])
            for label, other, edge in related:
                body.append(
                    f"- {label} **{md_text(node_label(other))}** ({md_code(source_ref(other))})  -  {md_text(edge.get('type', edge.get('label', 'relationship')))}; confidence: {md_text(edge.get('confidence', 'unknown'))}"
                )
            if not related:
                body.append("- No linked symbols in this snapshot.")
            body.append("")
        with (directory / f"{slugs[group]}.md").open("w", encoding="utf-8") as stream:
            stream.write("\n".join(body))


def search(graph: dict, query: str, limit: int = 30) -> list[dict]:
    if not isinstance(query, str) or len(query) > 500 or not 1 <= limit <= 100:
        raise ValueError("query must be <=500 characters and limit 1..100")
    nodes, _ = nodes_edges(graph)
    term = query.casefold()
    return [n for n in nodes if term in json.dumps(n, ensure_ascii=False).casefold()][
        :limit
    ]


def explain(graph: dict, ident: str) -> dict:
    nodes, edges = nodes_edges(graph)
    found = next((n for n in nodes if node_id(n) == ident), None)
    if found is None:
        raise ValueError("node not found")
    incoming, outgoing = [], []
    for edge in edges:
        src, dst = edge_ends(edge)
        if src == ident:
            outgoing.append({"node": by_node(nodes, dst), "edge": edge})
        if dst == ident:
            incoming.append({"node": by_node(nodes, src), "edge": edge})
    return {
        "node": found,
        "source": source_ref(found),
        "incoming": incoming[:100],
        "outgoing": outgoing[:100],
        "snapshot_only": True,
    }


def by_node(nodes: list[dict], ident: str) -> dict | None:
    return next((n for n in nodes if node_id(n) == ident), None)


def path_adjacency(
    nodes: list[dict], edges: list[dict], directed: bool
) -> dict[str, set[str]]:
    known = {node_id(n) for n in nodes}
    adjacency: dict[str, set[str]] = {ident: set() for ident in known}
    for edge in edges:
        source, target = edge_ends(edge)
        if source in known and target in known:
            adjacency[source].add(target)
            if not directed:
                adjacency[target].add(source)
    return adjacency


def bounded_bfs(
    adjacency: dict[str, set[str]], start: str, end: str, limit: int
) -> list[str] | None:
    queue = deque([(start, [start])])
    visited = {start}
    while queue:
        current, path = queue.popleft()
        if current == end:
            return path
        if len(path) >= limit + 1:
            continue
        for neighbor in sorted(adjacency[current]):
            if neighbor not in visited:
                visited.add(neighbor)
                queue.append((neighbor, path + [neighbor]))
    return None


def find_path(
    graph: dict, start: str, end: str, limit: int = 8, directed: bool = True
) -> list[str] | None:
    if not 1 <= limit <= 20:
        raise ValueError("path limit must be 1..20")
    nodes, edges = nodes_edges(graph)
    known = {node_id(n) for n in nodes}
    if start not in known or end not in known:
        raise ValueError("start or end node not found")
    return bounded_bfs(path_adjacency(nodes, edges, directed), start, end, limit)


def run_mcp(graph: dict) -> int:
    try:
        from mcp.server.fastmcp import FastMCP

        server = FastMCP("graphify-local-readonly")
    except ImportError:
        try:
            from mcp.server.mcpserver import MCPServer
        except ImportError as exc:
            raise RuntimeError(
                "MCP SDK is not installed in the selected Python environment"
            ) from exc
        server = MCPServer(name="graphify-local-readonly")

    @server.tool()
    def graph_query(query: str, limit: int = 30) -> list[dict]:
        """Search symbols and source metadata in the loaded local snapshot."""
        return search(graph, query, limit)

    @server.tool()
    def graph_node(node_id: str) -> dict:
        """Show one symbol, its source reference, and adjacent relationships."""
        return explain(graph, node_id)

    @server.tool()
    def graph_path(
        start: str, end: str, max_edges: int = 8, directed: bool = True
    ) -> dict:
        """Find a bounded shortest path through graph relationships."""
        return {
            "path": find_path(graph, start, end, max_edges, directed),
            "snapshot_only": True,
        }

    @server.tool()
    def graph_stats() -> dict:
        """Return graph counts and snapshot provenance/freshness limitations."""
        nodes, edges = nodes_edges(graph)
        return {
            "nodes": len(nodes),
            "edges": len(edges),
            "snapshot_only": True,
            "freshness": "This MCP process reads only the graph snapshot loaded at startup; restart it after source changes.",
        }

    server.run(transport="stdio")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    export = sub.add_parser("export")
    export.add_argument("graph", type=Path)
    export.add_argument("format", choices=("json", "html", "wiki"))
    export.add_argument("output", type=Path)
    mcp = sub.add_parser("mcp")
    mcp.add_argument("graph", type=Path)
    args = parser.parse_args(argv)
    try:
        graph_path = runtime_path(args.graph)
        graph = load_graph(graph_path)
        if args.command == "mcp":
            return run_mcp(graph)
        output = export_path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        if args.format == "json":
            with output.open("w", encoding="utf-8") as stream:
                stream.write(json.dumps(graph, ensure_ascii=False, indent=2) + "\n")
        elif args.format == "html":
            export_html(graph, output)
        else:
            export_wiki(graph, output)
    except (OSError, ValueError, TypeError, RuntimeError) as exc:
        print(f"graphify views: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
