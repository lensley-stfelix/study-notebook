from __future__ import annotations

import argparse
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime
from html import escape
import json
from pathlib import Path
from queue import Empty, Queue
import re
import sys
from tempfile import mkdtemp
from threading import Thread
from urllib.parse import urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup


COURSE = "https://study.com/academy/course/computer-science-302-system-analysis-design.html"
SAMPLE = "https://study.com/learn/lesson/systems-analysis-function-examples.html"
HEADING = "h1,h2,h3,h4,h5,h6,[role=heading]"
BLOCK = HEADING + ",p,li,dt,dd,pre,blockquote,tr"
CHAPTER = re.compile(r"(?:chapter|ch\.?)\s+(\d+)(?:\s*[:.\-–]\s*(.+))?", re.I)
LESSON_PATH = re.compile(r"/(?:academy|learn)/lesson/[^/]+\.html", re.I)
STOP = re.compile(
    r"learning outcomes|lesson quiz|take (?:the|a) quiz|practice quiz|"
    r"frequently asked questions|faq|related (?:lessons|courses)|"
    r"additional resources|lesson materials|lesson activities|up next",
    re.I,
)
GATE = re.compile(
    r"(?:register|sign up|log in|subscribe|become a member)\s+to\s+"
    r"(?:view|read|continue|unlock|access|watch)|(?:unlock|access)\s+"
    r"(?:the |this )?(?:full |entire )?(?:video )?transcript|"
    r"unlock (?:this|the full) lesson|create an account to (?:view|read|continue|unlock)|"
    r"this (?:lesson|video) is (?:a preview|locked)|end of (?:the |your )?preview|"
    r"(?:video |lesson )?preview only|verify (?:that )?you are human|access denied",
    re.I,
)


@dataclass(frozen=True)
class Lesson:
    url: str
    title: str = ""
    chapter: str = ""


@dataclass(frozen=True)
class Content:
    title: str
    kind: str
    blocks: list[tuple[str, str]]
    boundary: str


class Unavailable(Exception):
    pass


class AccessRestricted(Unavailable):
    pass


ACCESS_NOTICE = "Access is temporarily restricted"


def clean(value):
    return " ".join(value.split())


def node_text(node):
    return clean(node.get_text())


def study_url(value, base=COURSE, *, lesson=False):
    parsed = urlsplit(urljoin(base, value))
    if parsed.scheme != "https" or parsed.netloc.lower() not in {"study.com", "www.study.com"}:
        raise ValueError("expected an HTTPS Study.com URL")
    if lesson and not LESSON_PATH.fullmatch(parsed.path):
        raise ValueError("expected an /academy/lesson/ or /learn/lesson/ URL")
    return urlunsplit(("https", parsed.netloc.lower(), parsed.path, "" if lesson else parsed.query, ""))


def soup_of(markup):
    soup = BeautifulSoup(markup, "html.parser")
    for tag in soup.select("script,style,template,noscript,video,audio,[hidden],[aria-hidden=true]"):
        tag.decompose()
    return soup


def discover(markup, base):
    soup = soup_of(markup)
    chapter = ""
    lessons = []
    seen = set()
    for tag in soup.find_all(True):
        if tag.name in {"footer", "aside"} and chapter and lessons:
            break
        if tag.name == "a" and chapter and tag.get("href"):
            try:
                url = study_url(tag["href"], base, lesson=True)
            except ValueError:
                continue
            title = node_text(tag)
            key = urlsplit(url).path.rsplit("/", 1)[-1].lower()
            if title and key not in seen:
                seen.add(key)
                lessons.append(Lesson(url, title, chapter))
            continue
        if tag.name not in {"div", "span", "p", "strong", "b", "button", "summary", "h2", "h3", "h4", "h5"}:
            continue
        direct = clean(" ".join(str(part) for part in tag.find_all(string=True, recursive=False)))
        match = CHAPTER.fullmatch(direct) or CHAPTER.fullmatch(node_text(tag)[:120])
        if match and len(node_text(tag)) <= 120:
            number, name = match.groups()
            label = f"Chapter {number}"
            if name:
                chapter = f"{label} — {name}"
            elif not chapter.startswith(f"{label} —") and tag.find_parent(["header", "footer"]) is None:
                sibling = tag.find_next_sibling()
                candidate = node_text(sibling) if sibling and sibling.name in {"span", "div", "h2", "h3", "h4"} else ""
                if sibling and (sibling.find("a") or CHAPTER.match(candidate)):
                    candidate = ""
                chapter = f"{label} — {candidate}" if 0 < len(candidate) <= 100 else label
        if chapter and tag.name in {"h2", "h3"} and re.match(
            r"^(?:student reviews|course reviews|related courses|frequently asked questions)\b",
            direct,
            re.I,
        ):
            break
    return lessons


def read_outline(path):
    lessons = []
    seen = set()
    for number, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        fields = line.strip("\r\n").split("\t")
        if len(fields) == 1:
            chapter, title, url = "", "", fields[0]
        elif len(fields) == 3:
            chapter, title, url = fields
        else:
            raise ValueError(f"outline line {number} needs a URL or chapter, title and URL")
        url = study_url(url.strip(), lesson=True)
        if url not in seen:
            lessons.append(Lesson(url, clean(title), clean(chapter)))
            seen.add(url)
    return lessons


def extract(markup, *, confirmed_text_only=False):
    soup = soup_of(markup)
    if soup.find(string=lambda value: value and clean(value) == ACCESS_NOTICE):
        raise AccessRestricted(f"Study.com: {ACCESS_NOTICE}. Stop and contact Study.com support.")
    for tag in soup.select("nav,aside,footer,[role=navigation],form"):
        tag.decompose()
    title = soup.find("h1")
    if not title or not node_text(title):
        raise Unavailable("lesson title missing or page did not load")
    if GATE.search(node_text(title)):
        raise Unavailable("access or preview message in page title")
    for alert in soup.select("[role=dialog],[role=alertdialog],[role=alert]"):
        if GATE.search(node_text(alert)):
            raise Unavailable("visible access or preview message")
    headings = soup.select(HEADING)
    transcript = next((tag for tag in headings if node_text(tag).rstrip(":").lower() == "video transcript"), None)
    text_start = next(
        (tag for tag in headings if node_text(tag).rstrip(":").lower() in {"text-only lesson", "text lesson"}),
        None,
    )
    start = transcript or text_start
    if start is None and confirmed_text_only:
        if not GATE.search(node_text(soup)):
            start = title
    if start is None:
        reason = "visible access or preview message" if GATE.search(node_text(soup)) else "no visible Video Transcript or text-only heading"
        raise Unavailable(reason)
    kind = "video_transcript" if transcript else "text_only_lesson"
    dedicated = next(
        (
            parent for parent in start.parents
            if parent.name in {"section", "div", "article"}
            and re.search(r"(?:video[-_ ]+transcript|videotranscript|transcript[-_ ]+(?:content|body))",
                          " ".join([parent.get("id", ""), *parent.get("class", [])]), re.I)
        ),
        None,
    ) if transcript else None
    if dedicated is not None and len(dedicated.select("p,li")) < 1:
        dedicated = None
    container = dedicated
    if container is None and start is title:
        container = title.find_parent("article")
    nodes = container.select(BLOCK) if container else soup.select(BLOCK)
    positions = (index for index, tag in enumerate(nodes) if tag is start)
    index = next(positions, -1)
    if index < 0:
        raise Unavailable("content start fell outside the lesson section")
    blocks = []
    boundary = "dedicated lesson section" if container else ""
    eligible = {id(tag) for tag in nodes[index + 1:]}
    final_node = None
    for tag in nodes[index + 1:]:
        if any(id(parent) in eligible for parent in tag.parents):
            continue
        value = node_text(tag)
        if tag.name == "tr":
            value = " | ".join(node_text(cell) for cell in tag.find_all(["th", "td"], recursive=False))
        if not value:
            continue
        if GATE.search(value):
            raise Unavailable("access or preview message inside the lesson content")
        is_heading = tag.name.startswith("h") or tag.get("role") == "heading"
        if is_heading and (STOP.fullmatch(value.rstrip(":")) or CHAPTER.fullmatch(value)):
            boundary = value
            final_node = tag
            break
        if is_heading and value.rstrip(":").lower() == "video transcript":
            raise Unavailable("multiple transcript sections with an unclear boundary")
        if tag.has_attr("data-study-export-clipped") or tag.find_parent(attrs={"data-study-export-clipped": True}):
            raise Unavailable("lesson text is clipped in the browser")
        block_kind = "heading" if is_heading else {"li": "item", "pre": "code", "tr": "row"}.get(tag.name, "paragraph")
        blocks.append((block_kind, tag.get_text().strip() if block_kind == "code" else value))
        final_node = tag
    if final_node and boundary:
        scope = container.descendants if container and boundary == "dedicated lesson section" else start.next_elements
        for tag in scope:
            if tag is final_node and boundary != "dedicated lesson section":
                break
            if isinstance(tag, str) and GATE.search(clean(tag)):
                raise Unavailable("access or preview message before content end")
    if not boundary:
        raise Unavailable("could not verify where lesson content ends")
    if not any(block_kind != "heading" for block_kind, _ in blocks):
        raise Unavailable("lesson section has no visible text")
    return Content(node_text(title), kind, blocks, boundary)


VISIBLE_HTML = """() => {
    const clone = document.body.cloneNode(true);
    function prune(source, copy) {
        const sources = [...source.children];
        const copies = [...copy.children];
        sources.forEach((element, index) => {
            const style = getComputedStyle(element);
            if (element.hidden || element.getAttribute('aria-hidden') === 'true' ||
                style.display === 'none' || style.contentVisibility === 'hidden' ||
                Number(style.opacity) === 0 || style.visibility !== 'visible') {
                copies[index].remove();
            } else {
                if (/^(hidden|clip)$/.test(style.overflowY) &&
                    element.clientHeight > 0 && element.scrollHeight > element.clientHeight + 4) {
                    copies[index].setAttribute('data-study-export-clipped', '');
                }
                prune(element, copies[index]);
            }
        });
    }
    prune(document.body, clone);
    return clone.outerHTML;
}"""


@contextmanager
def browser(profile, channel):
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        context = playwright.chromium.launch_persistent_context(
            str(profile.resolve()), headless=False, service_workers="block", channel=channel,
            chromium_sandbox=True,
        )
        try:
            context.route("**/*", lambda route: route.abort() if
                          route.request.resource_type == "media" or re.search(
                              r"\.(?:m3u8|mpd|m4s|mp4|webm|ts|mp3|aac)(?:[?#]|$)",
                              route.request.url, re.I,
                          ) else route.continue_())
            yield context.pages[0] if context.pages else context.new_page()
        finally:
            context.close()


def wait_for_user(page, prompt):
    answers = Queue(maxsize=1)

    def read_console():
        try:
            input(prompt)
        except EOFError as exc:
            answers.put(exc)
        else:
            answers.put(None)

    Thread(target=read_console, daemon=True).start()
    while not page.is_closed():
        try:
            error = answers.get_nowait()
        except Empty:
            page.wait_for_timeout(100)
            continue
        if error:
            raise Unavailable("console input closed before browser setup was confirmed") from error
        return
    raise Unavailable("browser tab closed before setup was confirmed")


def navigate(page, url, *, setup=False):
    from playwright.sync_api import TimeoutError as NavigationTimeout

    try:
        response = page.goto(url, wait_until="commit" if setup else "domcontentloaded",
                             timeout=12000 if setup else 35000)
    except NavigationTimeout as exc:
        raise Unavailable(f"timed out opening {url}") from exc
    if response and response.status in {403, 429}:
        raise AccessRestricted(f"Study.com HTTP {response.status}. Stop and contact Study.com support if it persists.")
    if response and response.status >= 400:
        raise Unavailable(f"HTTP {response.status}")


def check_access_notice(page):
    notice = page.get_by_text(ACCESS_NOTICE, exact=True).first
    if notice.is_visible():
        raise AccessRestricted(f"Study.com: {ACCESS_NOTICE}. Stop and contact Study.com support.")


def load_lesson(page, lesson, text_only):
    navigate(page, lesson.url)
    try:
        study_url(page.url, lesson=True)
    except ValueError as exc:
        raise Unavailable("redirected away from a recognized lesson URL") from exc
    page.wait_for_timeout(1000)
    check_access_notice(page)
    heading = page.get_by_role("heading", name=re.compile(r"^Video Transcript:?$", re.I))
    if not any(item.is_visible() for item in heading.all()):
        button = page.get_by_role(
            "button", name=re.compile(r"^(?:show (?:video )?transcript|video transcript|transcript)$", re.I)
        )
        for item in button.all():
            if item.is_visible() and item.get_attribute("aria-expanded") != "true":
                item.click(timeout=4000)
                page.wait_for_timeout(750)
                break
    return extract(page.evaluate(VISIBLE_HTML), confirmed_text_only=text_only)


def markdown_text(value):
    return re.sub(r"([\\`*_{}\[\]<>#!|~])", r"\\\1", value)


def md_lesson(lesson, content, level):
    label = "Video transcript" if content.kind == "video_transcript" else "Text-only lesson"
    lines = [f"{'#' * level} {markdown_text(content.title)}", "", f"{label} · [Source](<{lesson.url}>)"]
    for kind, value in content.blocks:
        if kind == "code":
            fence = "`" * max(3, 1 + max((len(run) for run in re.findall(r"`+", value)), default=0))
            lines.extend(("", f"{fence}\n{value}\n{fence}"))
            continue
        prefix = {"heading": f"{'#' * (level + 1)} ", "item": "- "}.get(kind, "")
        rendered = markdown_text(value)
        if re.match(r"^(?:[-+>]|\d+[.)])\s", rendered):
            rendered = "\\" + rendered if not rendered[0].isdigit() else re.sub(r"^(\d+)([.)])", r"\1\\\2", rendered)
        lines.extend(("" if not (kind == "item" and lines[-1].startswith("- ")) else None, prefix + rendered))
    return "\n".join(line for line in lines if line is not None) + "\n"


def html_lesson(index, lesson, content):
    label = "Video transcript" if content.kind == "video_transcript" else "Text-only lesson"
    tags = {"heading": "h4", "item": "li", "code": "pre"}
    lines = [f'<article id="lesson-{index}"><h3>{escape(content.title)}</h3>',
             f'<p class="meta">{label} · <a href="{escape(lesson.url)}">Source</a></p>']
    in_list = False
    for kind, value in content.blocks:
        if (kind == "item") != in_list:
            in_list = kind == "item"
            lines.append("<ul>" if in_list else "</ul>")
        tag = tags.get(kind, "p")
        lines.append(f"<{tag}>{escape(value)}</{tag}>")
    if in_list:
        lines.append("</ul>")
    return "\n".join(lines + ["</article>"])


def write_reports(folder, manifest, exported):
    manifest_path = folder / "manifest.json"
    pending = folder / "manifest.tmp"
    pending.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    pending.replace(manifest_path)
    failures = [row for row in manifest["lessons"] if row["status"] != "exported"]
    headline = "Study.com offline lessons"
    status = f"{len(exported)} exported · {len(failures)} missing or pending"
    if manifest["coverage_note"]:
        status += " · " + manifest["coverage_note"]
    if manifest["run_note"]:
        status += " · " + manifest["run_note"]
    md = [f"# {headline}", "", markdown_text(status)]
    html = [
        '<!doctype html><html lang="en"><meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        f"<title>{headline}</title>",
        "<style>body{font:1rem/1.65 system-ui;max-width:74ch;margin:2rem auto;padding:0 1rem}"
        "article{border-top:1px solid #888;margin:2rem 0}pre{overflow:auto}.meta{opacity:.8}</style>",
        f"<main><h1>{headline}</h1><p>{escape(status)}</p>",
        '<p><a href="manifest.json">Export manifest</a></p>',
    ]
    if exported:
        html.append("<h2>Contents</h2><ol>")
        for index, _, content in exported:
            html.append(f'<li><a href="#lesson-{index}">{escape(content.title)}</a></li>')
        html.append("</ol>")
    last_chapter = None
    for index, lesson, content in exported:
        chapter = lesson.chapter or "Lessons"
        if chapter != last_chapter:
            md.extend(("", f"## {markdown_text(chapter)}"))
            html.append(f"<h2>{escape(chapter)}</h2>")
            last_chapter = chapter
        md.extend(("", md_lesson(lesson, content, 3)))
        html.append(html_lesson(index, lesson, content))
    (folder / "course.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    (folder / "course.html").write_text("\n".join(html + ["</main></html>"]), encoding="utf-8")


def cli():
    parser = argparse.ArgumentParser(description="Export visible Study.com lesson transcripts for offline study.")
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--course", help="Study.com course outline URL (defaults to CS 302)")
    source.add_argument("--lesson", action="append", help="specific lesson URL, repeatable")
    source.add_argument("--sample", action="store_true", help="export the supplied sample lesson")
    source.add_argument("--urls", type=Path, help="ordered UTF-8 lesson URL or tab-separated outline file")
    parser.add_argument("--expected-count", type=int, help="expected number of lessons in a full-course run")
    parser.add_argument("--text-only", action="append", default=[], metavar="URL",
                        help="confirm a specific lesson is text-only if it has no explicit text-only heading")
    parser.add_argument("--profile", type=Path, default=Path(".study-browser"))
    parser.add_argument("--channel", choices=["msedge", "chrome"], help="use an installed Edge or Chrome browser")
    parser.add_argument("--out", type=Path, default=Path("study-exports"))
    parser.add_argument("--delay", type=float, default=2, help="seconds between lesson loads (minimum 1)")
    args = parser.parse_args()
    if not 1 <= args.delay <= 300 or (args.expected_count is not None and args.expected_count < 1):
        parser.error("delay must be between 1 and 300 and expected count must be positive")
    try:
        course = study_url(args.course or COURSE)
        text_only = {study_url(url, lesson=True) for url in args.text_only}
        if args.urls:
            lessons = read_outline(args.urls)
            if not lessons:
                raise ValueError("outline file contains no lesson URLs")
        else:
            lessons = list(dict.fromkeys(
                Lesson(study_url(url, lesson=True))
                for url in (args.lesson or ([SAMPLE] if args.sample else []))
            ))
    except (ValueError, OSError) as exc:
        parser.error(str(exc))
    discovery = not lessons
    expected = args.expected_count
    if expected is None and discovery and course.split("?")[0] == COURSE:
        expected = 108
    args.out.mkdir(parents=True, exist_ok=True)
    folder = Path(mkdtemp(prefix=datetime.now().strftime("%Y%m%d-%H%M%S-"), dir=args.out)).resolve()
    (folder / "lessons").mkdir()
    print(f"Export folder: {folder}", flush=True)
    manifest = {"course_url": course if discovery else None, "expected_count": expected,
                "coverage_note": "Course outline not yet verified" if discovery else "",
                "run_note": "", "lessons": []}
    exported = []
    if lessons:
        manifest["lessons"] = [{**asdict(lesson), "status": "pending", "reason": "not yet attempted"}
                               for lesson in lessons]
    try:
        with browser(args.profile, args.channel) as page:
            try:
                navigate(page, course if discovery else lessons[0].url, setup=True)
            except AccessRestricted:
                raise
            except Unavailable as exc:
                print(f"{exc}. You can open the page manually in the browser window.", file=sys.stderr)
            check_access_notice(page)
            if discovery:
                print("In the browser, sign in if needed and open the course outline. Expand every chapter.")
                wait_for_user(page, "Press Enter here when the expanded outline is visible. ")
                check_access_notice(page)
                base = study_url(page.url)
                lessons = discover(page.evaluate(VISIBLE_HTML), base)
                if not lessons:
                    raise Unavailable("no lesson links found in the expanded outline; use --urls with ordered lesson links")
                print(f"Discovered {len(lessons)} lessons. Outline will be saved in outline.tsv.")
            else:
                wait_for_user(page, "When the lesson is visible in the browser, press Enter here to start. ")
                check_access_notice(page)
            manifest["coverage_note"] = (
                f"Found {len(lessons)} lesson URLs with {expected} expected"
                if expected is not None and len(lessons) != expected else ""
            )
            if manifest["coverage_note"]:
                print(manifest["coverage_note"], file=sys.stderr)
            rows = [{**asdict(lesson), "status": "pending", "reason": "not yet attempted"} for lesson in lessons]
            manifest["lessons"] = rows
            (folder / "outline.tsv").write_text(
                "".join(f"{lesson.chapter}\t{lesson.title}\t{lesson.url}\n" for lesson in lessons), encoding="utf-8"
            )
            write_reports(folder, manifest, exported)
            for index, (lesson, row) in enumerate(zip(lessons, rows), 1):
                if index > 1:
                    page.wait_for_timeout(args.delay * 1000)
                try:
                    content = load_lesson(page, lesson, lesson.url in text_only)
                    slug = re.sub(r"[^a-z0-9-]+", "-", urlsplit(lesson.url).path.rsplit("/", 1)[-1][:-5].lower())
                    relative = f"lessons/{index:03d}-{slug[:90]}.md"
                    (folder / relative).write_text(md_lesson(lesson, content, 1), encoding="utf-8")
                    exported.append((index, lesson, content))
                    row.update(status="exported", title=content.title, kind=content.kind, file=relative,
                               end_marker=content.boundary, reason=None)
                except Exception as exc:
                    reason = str(exc).splitlines()[0] if str(exc) else type(exc).__name__
                    row.update(status="missing", reason=reason)
                    if isinstance(exc, AccessRestricted) or page.is_closed():
                        raise Unavailable(reason) from exc
                finally:
                    write_reports(folder, manifest, exported)
                print(f"[{index}/{len(lessons)}] {row['status']} {row['title'] or lesson.url}"
                      + (f" · {row['reason']}" if row["reason"] else ""), flush=True)
    except (Exception, KeyboardInterrupt) as exc:
        manifest["run_note"] = str(exc).splitlines()[0] if str(exc) else type(exc).__name__
        print(f"Run stopped: {manifest['run_note']}", file=sys.stderr)
    finally:
        write_reports(folder, manifest, exported)
    print(f"Exported {len(exported)} of {len(lessons)} listed lessons. Reports: {folder}", flush=True)
    return 0 if exported and len(exported) == len(lessons) and not (
        manifest["coverage_note"] or manifest["run_note"]
    ) else 2


if __name__ == "__main__":
    sys.exit(cli())
