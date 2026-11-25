"""Offline companion notebook for manually collected lesson materials."""
from __future__ import annotations

import json
import re
import shutil
import tkinter as tk
import uuid
import webbrowser
from html import escape
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk

from PIL import Image, ImageGrab

IMAGES = {'.png', '.jpg', '.jpeg', '.gif', '.webp', '.bmp'}
VIDEOS = {'.mp4', '.webm', '.ogv', '.ogg', '.mov', '.m4v'}
MARKER = re.compile(r'\[\[media:([0-9a-f]{32})\]\]')


def new_lesson(root, title, text=''):
    folder = root / uuid.uuid4().hex
    folder.mkdir(parents=True)
    (folder / 'media').mkdir()
    note = {'title': title, 'text': text, 'media': {}}
    save_lesson(folder, note)
    return folder


def load_lesson(folder):
    return json.loads((folder / 'lesson.json').read_text(encoding='utf-8'))


def natural_key(value):
    return tuple((1, int(part)) if part.isdigit() else (0, part.casefold())
                 for part in re.split(r'(\d+)', str(value)))


def ordered_sources(paths):
    return sorted(map(Path, paths), key=lambda p: natural_key(p.as_posix()))


def read_source(source):
    text = source.read_text(encoding='utf-8-sig')
    heading = re.match(r'^#\s+(.+)', text)
    return heading.group(1) if heading else source.stem, text


def write_order(root, folders):
    temp = root / 'lesson-order.tmp'
    temp.write_text(json.dumps([folder.name for folder in folders]), encoding='utf-8')
    temp.replace(root / 'lesson-order.json')


def ordered_lessons(root):
    available = {p.name: p for p in root.iterdir() if not p.name.startswith('.')
                 and (p / 'lesson.json').is_file()}
    order_path = root / 'lesson-order.json'
    recorded = json.loads(order_path.read_text(encoding='utf-8')) if order_path.exists() else []
    result = [available.pop(name) for name in recorded if name in available]
    # Previous versions had no saved source names or ordering metadata.
    result.extend(sorted(available.values(), key=lambda p: (
        getattr(p.stat(), 'st_birthtime', p.stat().st_ctime), p.name)))
    write_order(root, result)
    return result


def match_source_order(folders, sources):
    """Reorder matched existing lessons without rewriting their contents."""
    by_title = {}
    for folder in folders:
        note = load_lesson(folder)
        by_title.setdefault(note['title'].strip().casefold(), []).append(folder)
    matched = []
    for source in ordered_sources(sources):
        title, _ = read_source(source)
        matches = by_title.get(title.strip().casefold(), [])
        if len(matches) == 1 and matches[0] not in matched:
            matched.append(matches[0])
    selected = set(matched)
    sequence = iter(matched)
    return [next(sequence) if folder in selected else folder for folder in folders], len(matched)


def trash_lesson(root, folder):
    if folder.parent != root or not (folder / 'lesson.json').is_file() or folder.name.startswith('.'):
        raise ValueError('Not an active lesson folder')
    trash = root / '.trash'
    trash.mkdir(exist_ok=True)
    target = trash / folder.name
    if target.exists():
        target = trash / uuid.uuid4().hex
    folder.rename(target)
    return target


def attach(folder, note, source=None, image=None):
    token = uuid.uuid4().hex
    if image is not None:
        suffix, label = '.png', 'Clipboard image.png'
    else:
        source = Path(source)
        suffix, label = source.suffix.lower(), source.name
        if suffix not in IMAGES | VIDEOS:
            raise ValueError('Choose a supported image or video file.')
    filename = token + suffix
    target = folder / 'media' / filename
    if image is not None:
        image.save(target, format='PNG')
    else:
        shutil.copy2(source, target)
    note['media'][token] = {'file': filename, 'label': label,
                            'kind': 'video' if suffix in VIDEOS else 'image'}
    return f'[[media:{token}]]'


def render(folder, note):
    pieces = []
    for index, part in enumerate(MARKER.split(note['text'])):
        if index % 2 == 0:
            pieces.append(f'<div class="text">{escape(part)}</div>')
            continue
        item = note['media'].get(part)
        if not item or not re.fullmatch(r'[0-9a-f]{32}\.[a-z0-9]+', item['file']):
            pieces.append('<p>Missing attachment</p>')
            continue
        path = 'media/' + item['file']
        label = escape(item['label'])
        if not (folder / path).is_file():
            pieces.append(f'<p>Missing attachment: {label}</p>')
        elif item['kind'] == 'video':
            pieces.append(f'<figure><video controls preload="metadata" src="{path}"></video>'
                          f'<figcaption>{label} · <a href="{path}">Open video file</a></figcaption></figure>')
        else:
            pieces.append(f'<figure><a href="{path}"><img src="{path}" alt="{label}"></a>'
                          f'<figcaption>{label}</figcaption></figure>')
    title = escape(note['title'])
    return ('<!doctype html><html lang="en"><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>{title}</title><style>body{{font:17px/1.6 system-ui;max-width:85ch;margin:2rem auto;padding:0 1rem}}'
            '.text{white-space:pre-wrap;overflow-wrap:anywhere}figure{margin:1.5rem 0}img,video{max-width:100%;max-height:75vh}'
            'figcaption{font-size:.85rem;color:#555}</style>'
            f'<main><h1>{title}</h1>{"".join(pieces)}</main></html>')


def save_lesson(folder, note):
    temp = folder / 'lesson.tmp'
    temp.write_text(json.dumps(note, ensure_ascii=False, indent=2), encoding='utf-8')
    temp.replace(folder / 'lesson.json')
    (folder / 'lesson.html').write_text(render(folder, note), encoding='utf-8')
    def markdown_media(match):
        item = note['media'].get(match.group(1))
        if not item:
            return '[Missing attachment]'
        label = item['label'].replace('[', '(').replace(']', ')')
        prefix = '!' if item['kind'] == 'image' else ''
        return f'\n{prefix}[{label}](media/{item["file"]})\n'
    (folder / 'lesson.md').write_text(MARKER.sub(markdown_media, note['text']), encoding='utf-8')


class Notebook:
    def __init__(self, window, root):
        self.window, self.root = window, root
        self.folder = self.note = None
        self.root.mkdir(parents=True, exist_ok=True)
        window.title('TESU Study Notebook — offline')
        window.geometry('1100x720')
        toolbar = ttk.Frame(window, padding=8)
        toolbar.pack(fill='x')
        for label, action in [('New lesson', self.create), ('Import text / Markdown', self.import_notes),
                              ('Save', self.save), ('Paste image', self.paste_image),
                              ('Attach image / video', self.add_files), ('Open lesson preview', self.preview)]:
            ttk.Button(toolbar, text=label, command=action).pack(side='left', padx=3)
        pane = ttk.Panedwindow(window, orient='horizontal')
        pane.pack(fill='both', expand=True, padx=8, pady=8)
        left = ttk.Frame(pane, padding=4)
        right = ttk.Frame(pane, padding=4)
        pane.add(left, weight=1)
        pane.add(right, weight=4)
        ttk.Label(left, text='Lessons').pack(anchor='w')
        self.listbox = tk.Listbox(left, exportselection=False, width=30)
        self.listbox.pack(fill='both', expand=True)
        self.listbox.bind('<<ListboxSelect>>', self.select)
        ordering = ttk.Frame(left)
        ordering.pack(fill='x', pady=4)
        ttk.Button(ordering, text='↑ Move up', command=lambda: self.move(-1)).pack(side='left', expand=True, fill='x')
        ttk.Button(ordering, text='↓ Move down', command=lambda: self.move(1)).pack(side='left', expand=True, fill='x')
        ttk.Button(left, text='Restore course order from files', command=self.reorder_from_files).pack(fill='x', pady=2)
        ttk.Button(left, text='Delete selected lesson', command=self.delete).pack(fill='x', pady=2)
        ttk.Button(left, text='Restore deleted lesson', command=self.restore).pack(fill='x', pady=2)
        self.title = tk.StringVar()
        ttk.Entry(right, textvariable=self.title).pack(fill='x', pady=(0, 8))
        ttk.Label(right, text='Paste notes here. Media markers appear at the cursor; open preview to view them.').pack(anchor='w')
        frame = ttk.Frame(right)
        frame.pack(fill='both', expand=True)
        self.editor = tk.Text(frame, wrap='word', undo=True, font=('Arial', 12))
        scroll = ttk.Scrollbar(frame, command=self.editor.yview)
        self.editor.configure(yscrollcommand=scroll.set)
        scroll.pack(side='right', fill='y')
        self.editor.pack(fill='both', expand=True)
        self.editor.bind('<Control-v>', self.on_paste)
        self.editor.bind('<Control-V>', self.on_paste)
        window.bind('<Control-s>', lambda event: self.save())
        window.protocol('WM_DELETE_WINDOW', self.close)
        self.refresh()
        if not self.folders:
            self.create('My first lesson')
        else:
            self.open(self.folders[0])

    def refresh(self):
        self.folders = ordered_lessons(self.root)
        self.listbox.delete(0, 'end')
        for index, p in enumerate(self.folders, 1):
            self.listbox.insert('end', f'{index}. {load_lesson(p)["title"]}')
        if self.folder in self.folders:
            self.listbox.selection_set(self.folders.index(self.folder))

    def save(self):
        if self.folder is None:
            return True
        self.note['title'] = self.title.get().strip() or 'Untitled lesson'
        self.note['text'] = self.editor.get('1.0', 'end-1c')
        try:
            save_lesson(self.folder, self.note)
        except OSError as exc:
            messagebox.showerror('Save failed', str(exc))
            return False
        return True

    def open(self, folder):
        self.folder, self.note = folder, load_lesson(folder)
        self.title.set(self.note['title'])
        self.editor.delete('1.0', 'end')
        self.editor.insert('1.0', self.note['text'])
        self.editor.edit_reset()
        self.refresh()

    def select(self, event=None):
        selection = self.listbox.curselection()
        if selection:
            folder = self.folders[selection[0]]
            if folder != self.folder and self.save():
                self.open(folder)

    def create(self, title=None):
        title = title or simpledialog.askstring('New lesson', 'Lesson title:')
        if title and self.save():
            self.open(new_lesson(self.root, title.strip() or 'Untitled lesson'))

    def import_notes(self):
        paths = filedialog.askopenfilenames(filetypes=[('Text and Markdown', '*.txt *.md'), ('All files', '*.*')])
        if not paths or not self.save():
            return
        for source in ordered_sources(paths):
            try:
                title, text = read_source(source)
                folder = new_lesson(self.root, title, text)
                write_order(self.root, self.folders + [folder])
                self.open(folder)
            except (OSError, UnicodeError) as exc:
                messagebox.showerror('Import failed', str(exc))

    def move(self, direction):
        if self.folder not in self.folders or not self.save():
            return
        index = self.folders.index(self.folder)
        dest = index + direction
        if 0 <= dest < len(self.folders):
            self.folders[index], self.folders[dest] = self.folders[dest], self.folders[index]
            write_order(self.root, self.folders)
            self.refresh()
            self.listbox.see(dest)

    def reorder_from_files(self):
        paths = filedialog.askopenfilenames(title='Select original lesson files in the course',
                                            filetypes=[('Text and Markdown', '*.txt *.md')])
        if not paths or not self.save():
            return
        try:
            result, count = match_source_order(self.folders, paths)
            write_order(self.root, result)
            self.refresh()
            messagebox.showinfo('Course order', f'Reordered {count} uniquely matched lessons. '
                                'Unmatched or duplicate titles remain in place; use Move up/down for those.')
        except (OSError, UnicodeError) as exc:
            messagebox.showerror('Reorder failed', str(exc))

    def delete(self):
        if self.folder is None or not messagebox.askyesno('Delete lesson',
                f'Move “{self.title.get()}” and its attachments to deleted lessons? You can restore it later.'):
            return
        if not self.save():
            return
        index = self.folders.index(self.folder)
        try:
            trash_lesson(self.root, self.folder)
        except (OSError, ValueError) as exc:
            messagebox.showerror('Delete failed', str(exc))
            return
        self.folder = self.note = None
        self.title.set('')
        self.editor.delete('1.0', 'end')
        self.refresh()
        if self.folders:
            self.open(self.folders[min(index, len(self.folders) - 1)])

    def restore(self):
        trash = self.root / '.trash'
        folders = sorted((p for p in trash.iterdir() if (p / 'lesson.json').is_file()),
                         key=lambda p: load_lesson(p)['title'].casefold()) if trash.exists() else []
        if not folders:
            messagebox.showinfo('Restore lesson', 'No deleted lessons.')
            return
        choices = '\n'.join(f'{i}. {load_lesson(p)["title"]}' for i, p in enumerate(folders, 1))
        number = simpledialog.askinteger('Restore lesson', 'Choose a lesson number:\n' + choices,
                                         minvalue=1, maxvalue=len(folders))
        if number is None or not self.save():
            return
        folder = folders[number - 1]
        target = self.root / folder.name
        if target.exists():
            target = self.root / uuid.uuid4().hex
        try:
            folder.rename(target)
            write_order(self.root, self.folders + [target])
            self.open(target)
        except OSError as exc:
            messagebox.showerror('Restore failed', str(exc))

    def insert_attachment(self, **kwargs):
        if self.folder is None:
            return
        try:
            marker = attach(self.folder, self.note, **kwargs)
            self.editor.insert('insert', '\n' + marker + '\n')
            self.save()
        except (OSError, ValueError) as exc:
            messagebox.showerror('Attachment failed', str(exc))

    def paste_image(self):
        try:
            image = ImageGrab.grabclipboard()
        except Exception as exc:
            messagebox.showerror('Clipboard unavailable', str(exc))
            return
        if isinstance(image, Image.Image):
            self.insert_attachment(image=image)
        else:
            messagebox.showinfo('Paste image', 'Copy an image or screenshot first, or use Attach image / video.')

    def on_paste(self, event):
        try:
            image = ImageGrab.grabclipboard()
        except Exception:
            return None
        if isinstance(image, Image.Image):
            self.insert_attachment(image=image)
            return 'break'
        return None

    def add_files(self):
        paths = filedialog.askopenfilenames(filetypes=[('Images and videos', ' '.join('*'+s for s in sorted(IMAGES | VIDEOS)))])
        for path in paths:
            self.insert_attachment(source=path)

    def preview(self):
        if self.folder and self.save():
            webbrowser.open((self.folder / 'lesson.html').resolve().as_uri())

    def close(self):
        if self.save():
            self.window.destroy()


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parent / 'notebook-data')
    args = parser.parse_args()
    window = tk.Tk()
    Notebook(window, args.root.resolve())
    window.mainloop()
