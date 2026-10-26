#~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
# ADVANCED SHIfT — Issue 001
# Cinema 4D Icon Browser
#
# Copyright (c) 2026 Maksym Vysokolov
#
# Author:    Maksym Vysokolov
# Website:   https://cataclysm-vfx.com
# Instagram: https://instagram.com/thodos998
#
# Free to use, modify, and redistribute under the MIT License.
# If you find this useful, consider following my work!
#~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
import time
import os
import posixpath
import tempfile
import c4d
from c4d import gui, plugins

SCAN_RANGES = ((0, 22000),)
MAX_SCAN_PER_RANGE = 100000

DEFAULT_ICON_SIZE = 40
MIN_ICON_SIZE = 20
MAX_ICON_SIZE = 80
ICON_STEP = 2
BUTTON_PADDING = 6
GRID_GAP = 6
INITIAL_VIEW_WIDTH = 0
VIEW_SAFETY = 4
RESIZE_POLL_MS = 50  #Detect column changes

ID_ROOT = 9000
ID_SEARCH = 9001
ID_FILTER = 9002
ID_STATS = 9003
ID_SCROLL = 9004
ID_CONTENT = 9005
ID_GRID = 9006
ID_FOOT = 9007
ID_SIZE_SLIDER = 9008
ID_SIZE_LABEL = 9009
ID_CONTROLS = 9010
ID_SIZE_GROUP = 9011
BUTTON_BASE = 100000


def icon_exists(icon_id):
    try:
        info = gui.GetIcon(icon_id)
        if not info or not isinstance(info, dict):
            return False
        bmp = info.get('bmp')
        return bmp is not None and bmp.GetBw() > 0 and bmp.GetBh() > 0
    except Exception:
        return False


def normalized_path(value):
    value = str(value or '').replace('\\', '/').strip()
    return posixpath.normpath(value).casefold() if value else ''


def inside_path(path, root):
    return bool(root) and (path == root or path.startswith(root.rstrip('/') + '/'))


def builtin_roots():
    startup = normalized_path(c4d.storage.GeGetStartupPath())
    resource = normalized_path(c4d.storage.GeGetC4DPath(c4d.C4D_PATH_RESOURCE))
    roots = [startup + '/corelibs'] if startup else []
    if resource:
        roots.extend((resource + '/modules', resource + '/mxn_plugins'))
    return tuple(roots)


def source_origin(filename, roots):
    path = normalized_path(filename)
    if not path:
        return 'unknown', 'No source filename: may be native or a user script'
    if any(inside_path(path, root) for root in roots):
        return 'c4d', 'Source is inside a shipped C4D module directory'
    extension = posixpath.splitext(path)[1]
    absolute = path.startswith('/') or (len(path) > 2 and path[1:3] == ':/')
    if absolute and extension in ('.pyp', '.pypv', '.xdl64', '.xlib', '.dylib', '.dll'):
        return 'external', 'Separate plugin module outside shipped C4D directories'
    return 'unknown', 'Source is not a recognized absolute plugin-module path'


def discover_icons():
    candidates = {}
    roots = builtin_roots()

    def add_candidate(value):
        if type(value) is not int or not (0 <= value <= 2147483647):
            return None
        return candidates.setdefault(value, {'symbols': set(), 'records': []})

    for name in dir(c4d):
        if name.startswith('_'):
            continue
        try:
            metadata = add_candidate(getattr(c4d, name))
        except (AttributeError, RuntimeError):
            continue
        if metadata is not None:
            metadata['symbols'].add(name)

    try:
        registered_plugins = plugins.FilterPluginList(c4d.PLUGINTYPE_ANY, False) or []
    except (AttributeError, RuntimeError) as exc:
        raise RuntimeError('Cannot classify icons: plugin enumeration failed') from exc

    for plugin in registered_plugins:
        try:
            metadata = add_candidate(plugin.GetID())
        except (AttributeError, RuntimeError, TypeError):
            continue
        if metadata is None:
            continue
        try:
            name = plugin.GetName() or ''
        except (AttributeError, RuntimeError):
            name = ''
        try:
            filename = str(plugin.GetFilename() or '')
        except (AttributeError, RuntimeError, TypeError):
            filename = ''
        origin, reason = source_origin(filename, roots)
        metadata['records'].append((origin, name, filename, reason))

    for start, end in SCAN_RANGES:
        if start < 0 or end < start or end - start + 1 > MAX_SCAN_PER_RANGE:
            raise ValueError('Invalid SCAN_RANGES segment: %r' % ((start, end),))
        for icon_id in range(start, end + 1):
            add_candidate(icon_id)

    result = []
    for icon_id, metadata in sorted(candidates.items()):
        if not icon_exists(icon_id):
            continue
        symbols, records = metadata['symbols'], metadata['records']
        origins = {record[0] for record in records if record[0] != 'unknown'}
        # Never let an unrelated c4d integer constant override a registration
        # Multiple registrations with conflicting origins cannot prove ownership
        origin = next(iter(origins)) if len(origins) == 1 else 'unknown'
        if not records:
            # Only explicit icon constants count as core evidence. Other c4d
            # constants may coincidentally have the same integer as an icon ID.
            core_symbols = [name for name in symbols if name.startswith('ICON_')]
            origin = 'c4d' if core_symbols else 'unknown'
            reason = ('C4D ICON_ symbol (no plugin registration)' if core_symbols
                      else 'No plugin registration or explicit C4D icon symbol')
        elif len(origins) > 1:
            reason = 'Conflicting plugin registrations for this icon ID'
        else:
            reason = '; '.join(sorted({record[3] for record in records}))
        result.append({
            'id': icon_id,
            'symbols': ', '.join(sorted(symbols)[:8]),
            'plugins': ', '.join(sorted({r[1] for r in records if r[1]})[:4]),
            'origin': origin,
            'origin_reason': reason,
            'source_files': '\n'.join(sorted({r[2] for r in records if r[2]})),
        })
    return result


class IconTile(gui.GeUserArea):
    def __init__(self, owner, item, size):
        super().__init__()
        self.owner = owner
        self.icon_id = item['id']
        self.symbols = item['symbols']
        self.plugins = item['plugins']
        self.origin = item['origin']
        self.origin_reason = item['origin_reason']
        self.source_files = item['source_files']
        self.size = size
        self.icon = None

    def GetMinSize(self):
        return self.size, self.size

    def DrawMsg(self, x1, y1, x2, y2, msg):
        w, h = self.GetWidth(), self.GetHeight()
        if w <= 0 or h <= 0:
            return
        self.OffScreenOn()
        self.SetClippingRegion(x1, y1, x2, y2)
        try:
            rgb = self.GetColorRGB(c4d.COLOR_BG)
            bg = c4d.Vector(rgb['r'], rgb['g'], rgb['b']) / 255.0
        except (AttributeError, RuntimeError, TypeError, KeyError):
            bg = c4d.Vector(0.19, 0.19, 0.19)

        selected = self.icon_id in self.owner.selected_icons
        hovered = self.owner.hovered_tile is self
        if selected:
            frame = c4d.Vector(0.54, 0.49, 0.91)
            thickness = 2
        elif hovered:
            frame = c4d.Vector(0.58, 0.58, 0.60)
            thickness = 2
        else:
            frame = c4d.Vector(0.11, 0.11, 0.11)
            thickness = 1

        self.DrawSetPen(frame)
        self.DrawRectangle(0, 0, w - 1, h - 1)
        self.DrawSetPen(bg)
        self.DrawRectangle(thickness, thickness,
                           max(thickness, w - thickness - 1),
                           max(thickness, h - thickness - 1))

        if self.icon is None:
            self.icon = gui.GetIcon(self.icon_id)
        data = self.icon
        if data and data.get('bmp') is not None:
            sw, sh = data['w'], data['h']
            if sw > 0 and sh > 0:
                available = max(1, min(w, h) - 6)
                scale = min(available / sw, available / sh)
                dw, dh = max(1, int(sw * scale)), max(1, int(sh * scale))
                self.DrawBitmap(
                    data['bmp'], (w - dw) // 2, (h - dh) // 2,
                    dw, dh, data['x'], data['y'], sw, sh,
                    c4d.BMP_NORMALSCALED | c4d.BMP_ALLOWALPHA,
                )

    def _image_drag_path(self):
        info = self.icon if self.icon is not None else gui.GetIcon(self.icon_id)
        if not info or info.get('bmp') is None:
            return None
        cache_dir = os.path.join(tempfile.gettempdir(), 'CVFX_C4D_IconBrowser')
        path = os.path.join(cache_dir, '%d.png' % self.icon_id)
        if os.path.isfile(path):
            return path
        os.makedirs(cache_dir, exist_ok=True)
        bmp = info['bmp'].GetClonePart(info['x'], info['y'], info['w'], info['h'])
        if bmp is None:
            return None
        saved = bmp.Save(path, c4d.FILTER_PNG)
        if saved != c4d.IMAGERESULT_OK or not os.path.isfile(path):
            print('[C4D Icons] Could not export icon %d: %s' % (self.icon_id, saved))
            return None
        return path

    def Message(self, msg, result):
        if msg.GetId() == c4d.BFM_GETCURSORINFO:
            self.owner.set_hover(self)
            result.SetId(c4d.BFM_GETCURSORINFO)
            result.SetInt32(c4d.RESULT_CURSOR, getattr(c4d, 'MOUSE_POINT_HAND', c4d.MOUSE_NORMAL))
            result.SetString(c4d.RESULT_BUBBLEHELP_TITLE, 'Icon ID: %d' % self.icon_id)
            tip = ['Origin: ' + {'c4d': 'Cinema 4D', 'external': 'External plugin',
                                  'unknown': 'Unassigned'}[self.origin],
                   self.origin_reason]
            if self.source_files:
                tip.append('Source: ' + self.source_files)
            if self.symbols:
                tip.append('Symbols: ' + self.symbols)
            if self.plugins:
                tip.append('Plugin: ' + self.plugins)
            tip.append(' |Click: copy ID |Drag: Drop into Icon')
            tip.append('Ctrl-click: toggle selection |Shift-click: select range')
            tip.append('Ctrl+Shift-click: add range |IDs copied with spaces')
            result.SetString(c4d.RESULT_BUBBLEHELP, '\n'.join(tip))
            return True
        if msg.GetId() == c4d.BFM_DRAGRECEIVE:
            try:
                if self.CheckDropArea(msg, True, True):
                    data = self.GetDragObject(msg)
                    if data and data.get('type') == c4d.DRAGTYPE_ATOMARRAY:
                        if msg.GetBool(c4d.BFM_DRAG_FINISHED):
                            self.owner.queue_object_drop(data.get('object'))
                            return True
                        return self.SetDragDestination(c4d.MOUSE_POINT_HAND)
            except (AttributeError, RuntimeError, TypeError, ValueError):
                pass
        return super().Message(msg, result)

    def InputEvent(self, msg):
        if (msg.GetInt32(c4d.BFM_INPUT_DEVICE) != c4d.BFM_INPUT_MOUSE or
                msg.GetInt32(c4d.BFM_INPUT_CHANNEL) != c4d.BFM_INPUT_MOUSELEFT or
                not msg.GetBool(c4d.BFM_INPUT_VALUE)):
            return False
        qualifiers = msg.GetInt32(c4d.BFM_INPUT_QUALIFIER)
        ctrl = bool(qualifiers & c4d.QCTRL)
        shift = bool(qualifiers & c4d.QSHIFT)
        if ctrl or shift:
            self.owner.copy_icon(self.icon_id, ctrl=ctrl, shift=shift)
            return True
        try:
            filename = self._image_drag_path()
            dragged = (self.HandleMouseDrag(
                msg, c4d.DRAGTYPE_FILENAME_IMAGE, filename, 0
            ) if filename else False)
        except (RuntimeError, TypeError, ValueError, OSError) as exc:
            print('[C4D Icons] Drag error (%d): %s' % (self.icon_id, exc))
            dragged = False
        if not dragged:
            self.owner.copy_icon(self.icon_id)
        return True


class RegisteredIconBrowser(gui.GeDialog):
    def __init__(self):
        super().__init__()
        self.icons = discover_icons()
        self.filtered = self.icons
        self.search = ''
        self.filter_mode = 0
        self.icon_size = DEFAULT_ICON_SIZE
        self.measured_stride = None  #calibrated from real native button x positions
        self.overflow_cap = None     #temporary upper limit when a wide icon is found
        self.overflow_view = None
        self.columns = self._count_columns(INITIAL_VIEW_WIDTH, self.icon_size)
        self.tile_areas = {}
        self.copied = None
        self.selected_icons = {}  # ordered IDs; preserves Ctrl-click order
        self.selection_anchor = None
        self.hovered_tile = None
        self.pending_drop = None
        self.last_drop_message = ''
        self.pending_icon_size = None
        self.last_slider_action = 0.0
        self.is_rebuilding = False
        self.has_layout = False

    def _count_columns(self, view_width, icon_size):
        if self.measured_stride is None:
            pitch = icon_size + 8.0  #only for initial layout
        else:
            #Preserve the actual C4D chrome/padding at different slider sizes
            pitch = max(1.0, self.measured_stride + (icon_size - self.icon_size))
        return max(1, int((max(1, view_width) - VIEW_SAFETY + GRID_GAP) // pitch))

    def _measure_native_stride(self):
        count = min(len(self.filtered), self.columns, 16)
        if count < 2:
            return
        positions = []
        for index in range(count):
            try:
                rect = self.GetItemDim(BUTTON_BASE + index)
                if isinstance(rect, dict) and rect.get('w', 0) > 0:
                    positions.append(int(rect['x']))
            except (RuntimeError, AttributeError, ValueError, KeyError, TypeError):
                pass
        if len(positions) < 2:
            return
        steps = [b - a for a, b in zip(positions, positions[1:]) if b > a]
        if not steps:
            return
        steps.sort()
        median = float(steps[len(steps) // 2])
        if self.icon_size <= median <= self.icon_size + 80:
            self.measured_stride = median

    def _grid_overflows(self):
        try:
            rect = self.GetItemDim(ID_GRID)
            if not rect or rect['w'] <= 0:
                return False
            return rect['w'] > self._view_width() - 1
        except (RuntimeError, AttributeError, ValueError, KeyError, TypeError):
            return False

    def _view_width(self):
        try:
            rect = self.GetVisibleArea(ID_SCROLL)
            if rect and rect['x2'] > rect['x1']:
                return rect['x2'] - rect['x1']
        except (KeyError, TypeError, RuntimeError, AttributeError):
            pass
        try:
            rect = self.GetItemDim(ID_SCROLL)
            if rect and rect['w'] > 0:
                return rect['w'] - 18  #reserved scrollbar width
        except (KeyError, TypeError, RuntimeError, AttributeError):
            pass
        return INITIAL_VIEW_WIDTH

    def CreateLayout(self):
        self.SetTitle('C4D Icon Browser | Multi-select')
        self.GroupBegin(ID_ROOT, c4d.BFH_SCALEFIT | c4d.BFV_SCALEFIT, cols=1)
        self.GroupBorderSpace(6, 6, 6, 6)
        self.GroupSpace(0, 6)

        self.GroupBegin(ID_CONTROLS, c4d.BFH_SCALEFIT | c4d.BFV_TOP, cols=2)
        self.GroupSpace(8, 0)
        self.AddEditText(ID_SEARCH, c4d.BFH_SCALEFIT, initw=0, editflags=c4d.EDITTEXT_ENABLECLEARBUTTON)
        self.AddComboBox(ID_FILTER, c4d.BFH_RIGHT, initw=0)
        self.AddChild(ID_FILTER, 0, 'All discovered icons')
        self.AddChild(ID_FILTER, 1, 'C4D + unassigned')
        self.AddChild(ID_FILTER, 2, 'External plugins only')
        self.AddChild(ID_FILTER, 3, 'Unassigned only')
        self.AddChild(ID_FILTER, 4, 'Confirmed C4D only')
        self.GroupEnd()

        self.ScrollGroupBegin(
            ID_SCROLL,
            c4d.BFH_SCALEFIT | c4d.BFV_SCALEFIT,
            c4d.SCROLLGROUP_VERT | c4d.SCROLLGROUP_AUTOVERT |
            c4d.SCROLLGROUP_HORIZ | c4d.SCROLLGROUP_AUTOHORIZ,
            initw=INITIAL_VIEW_WIDTH,
            inith=0,
        )
        self.GroupBegin(ID_CONTENT, c4d.BFH_LEFT | c4d.BFV_TOP, cols=1)
        self._build_grid()
        self.GroupEnd()  #content group
        self.GroupEnd()  #scroll group

        self.GroupBegin(ID_FOOT, c4d.BFH_SCALEFIT | c4d.BFV_BOTTOM, cols=2)
        self.GroupSpace(8, 0)
        self.AddStaticText(ID_STATS, c4d.BFH_SCALEFIT, name='')
        self.GroupBegin(ID_SIZE_GROUP, c4d.BFH_RIGHT | c4d.BFV_CENTER, cols=3)
        self.GroupSpace(7, 0)
        self.AddStaticText(0, c4d.BFH_RIGHT, name='Size')
        self.AddSlider(ID_SIZE_SLIDER, c4d.BFH_RIGHT, initw=150)
        self.AddStaticText(ID_SIZE_LABEL, c4d.BFH_RIGHT, initw=60,
                           name='%d px' % self.icon_size)
        self.GroupEnd()
        self.GroupEnd()  #footer
        self.GroupEnd()  #root
        self.has_layout = True
        return True

    def InitValues(self):
        self.SetString(ID_SEARCH, '')
        self.SetInt32(ID_FILTER, 0)
        self.SetInt32(ID_SIZE_SLIDER, self.icon_size,
                      min=MIN_ICON_SIZE, max=MAX_ICON_SIZE, step=ICON_STEP)
        self._update_stats()
        #Polling the viewport allows responsive columns when resizing the window
        #This is not an icon loader: every discovered button is already in the grid
        self.SetTimer(RESIZE_POLL_MS)
        return True

    def _build_grid(self):
        self.tile_areas.clear()
        self.hovered_tile = None
        self.GroupBegin(ID_GRID, c4d.BFH_LEFT | c4d.BFV_TOP, cols=self.columns)
        self.GroupSpace(GRID_GAP, GRID_GAP)

        if not self.filtered:
            self.AddStaticText(0, c4d.BFH_LEFT, name='No matching icons.')

        tile_size = self.icon_size + BUTTON_PADDING
        for index, item in enumerate(self.filtered):
            tile_id = BUTTON_BASE + index
            area = IconTile(self, item, tile_size)
            self.tile_areas[tile_id] = area
            self.AddUserArea(tile_id, c4d.BFH_LEFT | c4d.BFV_TOP,
                             tile_size, tile_size)
            self.AttachUserArea(area, tile_id)
        self.GroupEnd()

    def set_hover(self, tile):
        if self.hovered_tile is tile:
            return
        old = self.hovered_tile
        self.hovered_tile = tile
        if old is not None:
            old.Redraw()
        if tile is not None:
            tile.Redraw()

    def copy_icon(self, icon_id, ctrl=False, shift=False):
        previous = set(self.selected_icons)
        if shift:
            visible_ids = [item['id'] for item in self.filtered]
            if icon_id not in visible_ids:
                return
            if self.selection_anchor not in visible_ids:
                self.selection_anchor = icon_id
            first = visible_ids.index(self.selection_anchor)
            last = visible_ids.index(icon_id)
            lo, hi = sorted((first, last))
            if not ctrl:
                self.selected_icons.clear()
            for value in visible_ids[lo:hi + 1]:
                self.selected_icons[value] = None
        elif ctrl:
            if icon_id in self.selected_icons:
                del self.selected_icons[icon_id]
            else:
                self.selected_icons[icon_id] = None
            self.selection_anchor = icon_id
        else:
            self.selected_icons = {icon_id: None}
            self.selection_anchor = icon_id

        #Clipboard always reflects the complete selection, including IDs
        #selected in another filter/search. No duplicate IDs or trailing space.
        self.copied = ' '.join(str(value) for value in self.selected_icons)
        c4d.CopyStringToClipboard(self.copied)
        changed = previous.symmetric_difference(self.selected_icons)
        for tile in self.tile_areas.values():
            if tile.icon_id in changed:
                tile.Redraw()
        self._update_stats()

    def queue_object_drop(self, objects):
        if isinstance(objects, (list, tuple)) and objects:
            source = objects[0]
        else:
            return False
        if not isinstance(source, c4d.BaseList2D):
            return False
        value = None
        try:
            value = source[c4d.ID_BASELIST_ICON_FILE]
        except (AttributeError, RuntimeError, TypeError, KeyError):
            pass
        if value is not None:
            text = str(value).strip()
            if text.isdecimal():
                icon_id = int(text)
                origin = 'custom icon'
            else:
                icon_id = source.GetType()
                origin = 'type icon (no numeric custom icon)'
        else:
            icon_id = source.GetType()
            origin = 'type icon'
        if not isinstance(icon_id, int) or icon_id < 0:
            return False
        self.pending_drop = (str(icon_id), source.GetName(), origin)
        return True

    def _apply_pending_drop(self):
        if self.pending_drop is None:
            return
        icon_text, obj_name, origin = self.pending_drop
        self.pending_drop = None
        self.SetString(ID_SEARCH, icon_text)
        self.search = icon_text
        self._filter()
        self.last_drop_message = 'Dropped %s: %s (%s)' % (obj_name, icon_text, origin)
        self._update_stats()
        print('[C4D Icons]', self.last_drop_message)

    def Message(self, msg, result):
        if msg.GetId() == c4d.BFM_GETCURSORINFO:
            self.set_hover(None)
        if msg.GetId() == c4d.BFM_DRAGRECEIVE:
            try:
                if self.CheckDropArea(ID_ROOT, msg, True, True):
                    data = self.GetDragObject(msg)
                    if data and data.get('type') == c4d.DRAGTYPE_ATOMARRAY:
                        if msg.GetBool(c4d.BFM_DRAG_FINISHED):
                            if self.queue_object_drop(data.get('object')):
                                return True
                        else:
                            return self.SetDragDestination(c4d.MOUSE_POINT_HAND)
            except (AttributeError, RuntimeError, ValueError, TypeError):
                pass
        return super().Message(msg, result)

    def _update_stats(self):
        message = '%d / %d icons  |  Ctrl: toggle  |  Shift: range  |  drag: PNG' % (len(self.filtered), len(self.icons))
        if self.selected_icons:
            visible = {item['id'] for item in self.filtered}
            hidden = sum(value not in visible for value in self.selected_icons)
            message += '  |  Selected: %d' % len(self.selected_icons)
            if hidden:
                message += ' (%d hidden)' % hidden
        if self.copied is not None:
            message += ('  |  Copied: %s' % self.copied if len(self.selected_icons) == 1
                        else '  |  Copied %d IDs' % len(self.selected_icons))
        if self.last_drop_message:
            message += '  |  ' + self.last_drop_message
        self.SetString(ID_STATS, message)

    def _rebuild(self, new_icon_size=None, new_columns=None, keep_position=True):
        if self.is_rebuilding:
            return

        old_size = self.icon_size
        old_columns = self.columns
        old_row_stride = old_size + BUTTON_PADDING + GRID_GAP
        visible_anchor = 0
        if keep_position:
            try:
                rect = self.GetVisibleArea(ID_SCROLL)
                visible_anchor = max(0, int(rect['y1'] // old_row_stride)) * old_columns
            except (KeyError, TypeError, RuntimeError, AttributeError):
                pass

        next_size = self.icon_size if new_icon_size is None else int(new_icon_size)
        next_cols = self._count_columns(self._view_width(), next_size) \
            if new_columns is None else int(new_columns)
        if next_size == old_size and next_cols == old_columns and keep_position:
            return

        self.is_rebuilding = True
        try:
            if not self.LayoutFlushGroup(ID_CONTENT):
                return
            self.icon_size = next_size
            if next_size != old_size:
                self.overflow_cap = None
                self.overflow_view = None
            if next_size != old_size and self.measured_stride is not None:
                self.measured_stride += next_size - old_size
            self.columns = next_cols
            self._build_grid()
            self.GroupEnd()  #closes the reopened content group
            self.LayoutChanged(ID_CONTENT)

            if keep_position and visible_anchor:
                new_row = visible_anchor // next_cols
                target_y = new_row * (next_size + BUTTON_PADDING + GRID_GAP)
                try:
                    self.SetVisibleArea(ID_SCROLL, 0, target_y, 1, target_y + 1)
                except (AttributeError, RuntimeError):
                    pass
        finally:
            self.is_rebuilding = False
        self._update_stats()

    def _filter(self):
        q = self.search.strip().casefold()
        self.filtered = [
            item for item in self.icons
            if ((self.filter_mode == 0)
                or (self.filter_mode == 1 and item['origin'] != 'external')
                or (self.filter_mode == 2 and item['origin'] == 'external')
                or (self.filter_mode == 3 and item['origin'] == 'unknown')
                or (self.filter_mode == 4 and item['origin'] == 'c4d'))
            and (not q or q in str(item['id'])
                 or q in item['symbols'].casefold()
                 or q in item['plugins'].casefold())
        ]
        self.copied = None
        self.overflow_cap = None
        self.overflow_view = None
        self._rebuild(new_columns=self._count_columns(self._view_width(), self.icon_size),
                      keep_position=False)
        try:
            self.SetVisibleArea(ID_SCROLL, 0, 0, 1, 1)
        except (AttributeError, RuntimeError):
            pass

    def Timer(self, msg):
        if not self.has_layout or self.is_rebuilding:
            return
        if self.pending_drop is not None:
            self._apply_pending_drop()
            return

        if self.pending_icon_size is not None:
            #Avoid destroying/recreating thousands of controls DURING a slider drag
            #Apply size after the user stops dragging for 450 ms.
            if time.monotonic() - self.last_slider_action >= 0.45:
                size = self.pending_icon_size
                self.pending_icon_size = None
                if size != self.icon_size:
                    self._rebuild(new_icon_size=size)
                return

        self._measure_native_stride()
        view_width = self._view_width()
        if (self.overflow_view is not None and
                abs(view_width - self.overflow_view) > 3):
            #Re-evaluate once the window is resized
            self.overflow_cap = None
            self.overflow_view = None

        cols = self._count_columns(view_width, self.icon_size)
        if self._grid_overflows() and self.columns > 1:
            #Intrinsically wide icon still forcing the layout? Reduce the
            #number of columns and remember the cap until size/width changes
            self.overflow_cap = self.columns - 1
            self.overflow_view = view_width
        if self.overflow_cap is not None:
            cols = min(cols, self.overflow_cap)
        if cols != self.columns:
            self._rebuild(new_columns=cols)

    def Command(self, cid, msg):
        if cid == ID_SEARCH:
            self.search = self.GetString(ID_SEARCH) or ''
            self._filter()
            return True
        if cid == ID_FILTER:
            self.filter_mode = int(self.GetInt32(ID_FILTER))
            self._filter()
            return True
        if cid == ID_SIZE_SLIDER:
            new_size = self.GetInt32(ID_SIZE_SLIDER)
            if new_size is None:
                return True
            new_size = max(MIN_ICON_SIZE, min(MAX_ICON_SIZE, int(new_size)))
            self.SetString(ID_SIZE_LABEL, '%d px' % new_size)
            self.pending_icon_size = new_size
            self.last_slider_action = time.monotonic()
            try:
                dragging = bool(msg.GetBool(c4d.BFM_ACTION_INDRAG))
            except (AttributeError, RuntimeError):
                dragging = False
            if not dragging:
                self.pending_icon_size = None
                self._rebuild(new_icon_size=new_size)
            return True
        return False


if __name__ == '__main__':
    _c4d_registered_icon_browser = RegisteredIconBrowser()
    _c4d_registered_icon_browser.Open(
        dlgtype=c4d.DLG_TYPE_ASYNC,
        defaultw=780,
        defaulth=660,
    )
