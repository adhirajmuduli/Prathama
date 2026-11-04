// AG Grid globals
let gridOptions;

const GRID_MIN_ROWS = 100;
const GRID_MIN_COLUMNS = 100;
const DEFAULT_PARAMETER_NAME = "Parameter 1";
const PADDING_PARAMETER_NAME = "New Parameter";
let draftColumns = [];
let draftRows = [];

const INITIAL_ROWS = 0;
const DEFAULT_PARAMETER = 'Parameter 1';

function todayIso() {
  return new Date().toISOString().slice(0, 10);
}

function nextDate(dates) {
  const latest = dates.filter(Boolean).sort().pop();
  const date = latest ? new Date(`${latest}T00:00:00Z`) : new Date();
  date.setUTCDate(date.getUTCDate() + 1);
  return date.toISOString().slice(0, 10);
}

function displayDate(iso) {
  const [year, month, day] = iso.split('-');
  return `${day}/${month}/${year}`;
}

function fieldName(parameter, iso) {
  return `${parameter}_${iso}`;
}

function splitField(field) {
  const index = field.lastIndexOf('_');
  return index > 0 ? { parameter: field.slice(0, index), iso: field.slice(index + 1) } : null;
}

function showStatus(message, color = '#0078d4') {
  const element = document.getElementById('status');
  if (!element) return;
  element.textContent = message;
  element.style.color = color;
  element.className = color === 'red' ? 'error' : color === 'orange' ? 'warning' : color === 'green' ? 'success' : 'info';
}

function button(label, title, handler, className = 'grid-action') {
  const control = document.createElement('button');
  control.type = 'button';
  control.className = className;
  control.textContent = label;
  control.title = title;
  control.setAttribute('aria-label', title);
  ['pointerdown', 'mousedown', 'click'].forEach((eventName) => {
    control.addEventListener(eventName, (event) => {
      event.stopPropagation();
      if (eventName === 'click') handler(event);
    });
  });
  return control;
}

function dateHeader(params) {
  const root = document.createElement('div');
  root.className = 'date-header';
  const input = document.createElement('input');
  input.type = 'date';
  input.value = params.colDef.iso;
  input.title = 'Change timestamp';
  input.setAttribute('aria-label', `Change timestamp ${params.colDef.iso}`);
  input.addEventListener('change', () => renameDate(params.colDef, input.value));
  const remove = button('-', 'Delete timestamp column', () => removeTimestamp(params.colDef));
  root.append(input, remove);
  return root;
}

function parameterHeader(params) {
  const root = document.createElement('div');
  root.className = 'parameter-header';
  const label = document.createElement('span');
  label.textContent = params.displayName;
  label.title = 'Double-click to rename parameter';
  label.addEventListener('dblclick', () => {
    const name = window.prompt('Parameter name', params.displayName)?.trim();
    if (name && name !== params.displayName) renameParameter(params.displayName, name);
  });
  root.append(label, button('-', 'Delete parameter group', () => removeParameter(params.displayName)));
  return root;
}

function rowTools(params) {
  return button('-', 'Delete coordinate row', async () => {
    const row = params.node.data;
    const hasSavedStation = row.station_id !== undefined && row.station_id !== null;
    if (hasSavedStation) {
      const response = await fetch('/api/table/delete-station', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ latitude: row.latitude, longitude: row.longitude }),
      });
      if (!response.ok && response.status !== 404) {
        const result = await response.json().catch(() => ({}));
        showStatus(result.detail || 'Could not delete coordinate row.', 'red');
        return;
      }
    }
    draftRows = draftRows.filter((item) => item !== row);
    gridOptions.api.applyTransaction({ remove: [row] });
    showStatus('Coordinate row deleted.', 'green');
  }, 'grid-minus');
}

function makeColumn(parameter, iso) {
  return {
    field: fieldName(parameter, iso),
    headerName: displayDate(iso),
    parameter,
    iso,
    editable: true,
    width: 138,
    minWidth: 120,
    headerComponent: 'dateHeader',
  };
}

function parameterGroups() {
  return [...new Set(draftColumns.map((column) => column.parameter))];
}

function rebuildColumns() {
  const groups = parameterGroups().map((parameter) => ({
    headerName: parameter,
    marryChildren: true,
    headerGroupComponent: 'parameterHeader',
    children: draftColumns.filter((column) => column.parameter === parameter),
  }));
  gridOptions.api.setColumnDefs([
    { colId: '__row_tools__', headerName: '', pinned: 'left', width: 48, editable: false, cellRenderer: 'rowTools', suppressMovable: true },
    { field: 'latitude', headerName: 'Latitude', pinned: 'left', width: 120, editable: true },
    { field: 'longitude', headerName: 'Longitude', pinned: 'left', width: 120, editable: true },
    ...groups,
  ]);
  gridOptions.api.refreshHeader();
}

function renameDate(column, newIso) {
  if (!newIso || newIso === column.iso) return;
  if (draftColumns.some((item) => item.parameter === column.parameter && item.iso === newIso)) {
    showStatus('That parameter already has this timestamp.', 'red');
    rebuildColumns();
    return;
  }
  const oldField = column.field;
  const newField = fieldName(column.parameter, newIso);
  draftRows.forEach((row) => {
    if (Object.prototype.hasOwnProperty.call(row, oldField)) {
      row[newField] = row[oldField];
      delete row[oldField];
    }
  });
  column.iso = newIso;
  column.field = newField;
  column.headerName = displayDate(newIso);
  draftColumns.sort((a, b) => a.iso.localeCompare(b.iso));
  rebuildColumns();
  gridOptions.api.setRowData(draftRows);
  showStatus(`Timestamp changed to ${displayDate(newIso)}.`, 'green');
}

function removeTimestamp(column) {
  draftColumns = draftColumns.filter((item) => item !== column);
  draftRows.forEach((row) => delete row[column.field]);
  rebuildColumns();
  gridOptions.api.setRowData(draftRows);
  showStatus('Timestamp column deleted.', 'green');
}

function renameParameter(oldName, newName) {
  if (parameterGroups().includes(newName)) {
    showStatus('That parameter already exists.', 'red');
    return;
  }
  draftColumns.filter((column) => column.parameter === oldName).forEach((column) => {
    const oldField = column.field;
    column.parameter = newName;
    column.field = fieldName(newName, column.iso);
    draftRows.forEach((row) => {
      if (Object.prototype.hasOwnProperty.call(row, oldField)) {
        row[column.field] = row[oldField];
        delete row[oldField];
      }
    });
  });
  rebuildColumns();
  gridOptions.api.setRowData(draftRows);
}

function removeParameter(parameter) {
  const columns = draftColumns.filter((column) => column.parameter === parameter);
  draftColumns = draftColumns.filter((column) => column.parameter !== parameter);
  draftRows.forEach((row) => columns.forEach((column) => delete row[column.field]));
  rebuildColumns();
  gridOptions.api.setRowData(draftRows);
  showStatus(`Parameter "${parameter}" deleted.`, 'green');
}

function openTimestampPicker() {
  const dialog = document.getElementById('timestamp-dialog');
  const list = document.getElementById('timestamp-parameters');
  list.replaceChildren();
  parameterGroups().forEach((parameter, index) => {
    const label = document.createElement('label');
    const checkbox = document.createElement('input');
    checkbox.type = 'checkbox';
    checkbox.value = parameter;
    checkbox.checked = index === 0;
    label.append(checkbox, document.createTextNode(parameter));
    list.append(label);
  });
  document.getElementById('timestamp-value').value = nextDate(draftColumns.map((column) => column.iso));
  dialog.showModal();
}

function addTimestamp() {
  const dialog = document.getElementById('timestamp-dialog');
  const iso = document.getElementById('timestamp-value').value;
  const selected = [...document.querySelectorAll('#timestamp-parameters input:checked')].map((input) => input.value);
  if (!iso || selected.length === 0) return;
  selected.forEach((parameter) => {
    if (!draftColumns.some((column) => column.parameter === parameter && column.iso === iso)) {
      draftColumns.push(makeColumn(parameter, iso));
    }
  });
  rebuildColumns();
  showStatus(`Added ${displayDate(iso)} to ${selected.length} parameter(s).`, 'green');
  dialog.close();
}

function addParameter() {
  const name = window.prompt('Parameter name', `Parameter ${parameterGroups().length + 1}`)?.trim();
  if (!name || parameterGroups().includes(name)) return;
  draftColumns.push(makeColumn(name, todayIso()));
  rebuildColumns();
  showStatus(`Parameter "${name}" added.`, 'green');
}

function addRow() {
  const row = { latitude: '', longitude: '' };
  draftRows.push(row);
  gridOptions.api.applyTransaction({ add: [row] });
  const index = gridOptions.api.getDisplayedRowCount() - 1;
  gridOptions.api.ensureIndexVisible(index, 'bottom');
  gridOptions.api.setFocusedCell(index, 'latitude');
  showStatus('New coordinate row added.', 'green');
}

function buildDraft(pivoted) {
  const columns = [];
  const rows = (pivoted || []).map((source) => ({ ...source }));
  (pivoted || []).forEach((row) => Object.keys(row).forEach((key) => {
    const parts = splitField(key);
    if (parts && !columns.some((column) => column.field === key)) columns.push(makeColumn(parts.parameter, parts.iso));
  }));
  if (!columns.length) columns.push(makeColumn(DEFAULT_PARAMETER, todayIso()));
  while (rows.length < INITIAL_ROWS) rows.push({ latitude: '', longitude: '' });
  draftColumns = columns;
  draftRows = rows;
}

async function loadGrid() {
  try {
    const response = await fetch('/api/table');
    if (!response.ok) throw new Error(`Unable to load table (${response.status})`);
    buildDraft(await response.json());
    rebuildColumns();
    gridOptions.api.setRowData(draftRows);
    showStatus('Spreadsheet ready. Changes are saved when you click Save & Return.', 'green');
  } catch (error) {
    showStatus(error.message, 'red');
  }
}

async function saveTable() {
  gridOptions.api.stopEditing();
  const observations = [];
  draftRows.forEach((row) => {
    const latitude = Number(row.latitude);
    const longitude = Number(row.longitude);
    if (!Number.isFinite(latitude) || !Number.isFinite(longitude)) return;
    draftColumns.forEach((column) => {
      const value = Number(row[column.field]);
      if (Number.isFinite(value)) observations.push({ latitude, longitude, parameter: column.parameter, timestamp: column.iso, value });
    });
  });
  if (!observations.length) return showStatus('Enter coordinates and at least one numeric measurement.', 'orange');
  showStatus(`Saving ${observations.length} measurements...`);
  const response = await fetch('/api/table', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(observations) });
  const result = await response.json().catch(() => ({}));
  if (!response.ok) return showStatus(result.detail || result.error || 'Save failed.', 'red');
  sessionStorage.setItem('trendsmapp_last_dataset', JSON.stringify({ data: observations, message: `Imported ${observations.length} measurements from data-entry table.` }));
  showStatus('Saved. Returning to map...', 'green');
  setTimeout(() => { window.location.href = '/'; }, 800);
}

function initialize() {
  const gridDiv = document.getElementById('data-grid');
  gridOptions = {
    columnDefs: [], rowData: [], components: { dateHeader, parameterHeader, rowTools },
    defaultColDef: { resizable: true, sortable: true, filter: true },
    stopEditingWhenCellsLoseFocus: true, undoRedoCellEditing: true, undoRedoCellEditingLimit: 50,
    suppressMovableColumns: true, onGridReady: (params) => { gridOptions.api = params.api; loadGrid(); },
  };
  new agGrid.Grid(gridDiv, gridOptions);
  document.getElementById('btn-add-param').addEventListener('click', addParameter);
  document.getElementById('btn-add-timestamp').addEventListener('click', openTimestampPicker);
  document.getElementById('btn-add-coordinate').addEventListener('click', addRow);
  document.getElementById('btn-save').addEventListener('click', saveTable);
  document.getElementById('timestamp-cancel').addEventListener('click', () => document.getElementById('timestamp-dialog').close());
  document.getElementById('timestamp-add').addEventListener('click', addTimestamp);
}

if (typeof agGrid === 'undefined') showStatus('AG Grid failed to load.', 'red');
else initialize();

/* Legacy implementation retained below for history; the draft-based pipeline above is authoritative.
window.onerror = function(message, source, lineno, colno, error) {
  console.error('Global error:', {message, source, lineno, colno, error});
  const statusEl = document.getElementById('status');
  if (statusEl) {
    statusEl.textContent = 'Error: ' + (error ? error.message : message);
    statusEl.style.color = 'red';
  }
};

async function mutateTable(url, payload) {
  const response = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  const result = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(result.error || `Request failed (${response.status})`);
  }
  await loadAndConfigureGrid();
  return result;
}

// ---------------------------------------------------------------------------
// Date helpers: ISO 8601 storage/transfer, dd/mm/yyyy display.
// ---------------------------------------------------------------------------

function isoToDate(iso) {
  return new Date(`${iso}T00:00:00Z`);
}

function toIso(date) {
  return date.toISOString().slice(0, 10);
}

function todayIso() {
  return toIso(new Date());
}

function formatDisplayDate(iso) {
  const date = isoToDate(iso);
  const day = String(date.getUTCDate()).padStart(2, '0');
  const month = String(date.getUTCMonth() + 1).padStart(2, '0');
  return `${day}/${month}/${date.getUTCFullYear()}`;
}

function nextIsoAfter(isoValues) {
  const latest = isoValues.reduce((acc, value) => (value > acc ? value : acc), '');
  const base = latest ? isoToDate(latest) : isoToDate(todayIso());
  base.setUTCDate(base.getUTCDate() + 1);
  return toIso(base);
}

function splitFieldName(field) {
  const separatorIndex = field.lastIndexOf('_');
  if (separatorIndex <= 0) return null;
  return { parameter: field.slice(0, separatorIndex), iso: field.slice(separatorIndex + 1) };
}

function createCalendarIcon() {
  const svgNamespace = 'http://www.w3.org/2000/svg';
  const svg = document.createElementNS(svgNamespace, 'svg');
  svg.setAttribute('viewBox', '0 0 24 24');
  svg.setAttribute('width', '14');
  svg.setAttribute('height', '14');
  svg.setAttribute('aria-hidden', 'true');
  const path = document.createElementNS(svgNamespace, 'path');
  path.setAttribute('fill', 'currentColor');
  path.setAttribute(
    'd',
    'M19 4h-1V2h-2v2H8V2H6v2H5a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V6a2 2 0 0 0-2-2zm0 16H5V10h14zm0-12H5V6h14z'
  );
  svg.appendChild(path);
  return svg;
}

function createMinusButton(title, onClick) {
  const button = document.createElement('button');
  button.type = 'button';
  button.className = 'grid-minus';
  button.textContent = '\u2212';
  button.title = title;
  button.setAttribute('aria-label', title);
  button.addEventListener('mousedown', (event) => event.stopPropagation());
  button.addEventListener('pointerdown', (event) => event.stopPropagation());
  button.addEventListener('click', (event) => {
    event.preventDefault();
    event.stopPropagation();
    onClick(event);
  });
  return button;
}

// ---------------------------------------------------------------------------
// Inline Date Cell Editor - allows editing date values in cells
// ---------------------------------------------------------------------------

class DateCellEditor {
  init(params) {
    this.params = params;
    this.container = document.createElement('div');
    this.container.style.width = '100%';
    this.container.style.height = '100%';
    this.container.style.display = 'flex';
    this.container.style.alignItems = 'center';

    this.input = document.createElement('input');
    this.input.type = 'date';
    this.input.style.width = '100%';
    this.input.style.height = '100%';
    this.input.style.padding = '4px';
    this.input.style.border = '1px solid #0078d4';
    this.input.style.fontSize = '14px';
    this.input.setAttribute('aria-label', 'Edit date value');

    // Try to parse the current value as an ISO date
    const currentValue = params.value;
    if (currentValue && this.looksLikeDate(String(currentValue))) {
      this.input.value = String(currentValue).substring(0, 10);
    }

    this.container.appendChild(this.input);

  }

  looksLikeDate(value) {
    return /^\d{4}-\d{2}-\d{2}/.test(value);
  }

  getGui() {
    return this.container;
  }

  getValue() {
    return this.input.value || this.params.value;
  }

  isPopup() {
    return false;
  }

  destroy() {}
}

// ---------------------------------------------------------------------------
// Custom AG Grid components (registered by name in gridOptions.components).
// ---------------------------------------------------------------------------

class DateHeader {
  init(params) {
    const colDef = params.colDef || {};
    const isoDate = colDef.isoDate || '';

    this.gui = document.createElement('div');
    this.gui.className = 'date-header';

    const label = document.createElement('span');
    label.className = 'date-label';
    label.textContent = isoDate ? formatDisplayDate(isoDate) : (params.displayName || '');

    const pickerWrap = document.createElement('span');
    pickerWrap.className = 'cal-wrap';
    pickerWrap.title = 'Pick a new date for this column';
    pickerWrap.appendChild(createCalendarIcon());

    const calendar = document.createElement('input');
    calendar.type = 'date';
    calendar.className = 'cal-native';
    calendar.setAttribute('tabindex', '0');
    calendar.setAttribute('aria-label', `Edit timestamp ${isoDate}`);
    if (isoDate) calendar.value = isoDate;
    calendar.addEventListener('mousedown', (event) => event.stopPropagation());
    calendar.addEventListener('pointerdown', (event) => event.stopPropagation());
    calendar.addEventListener('click', (event) => event.stopPropagation());
    calendar.addEventListener('change', () => {
      const chosen = calendar.value;
      if (!chosen || chosen === isoDate) return;
      const context = params.context;
      if (context && typeof context.onDateChange === 'function') {
        context.onDateChange(colDef, chosen, calendar);
      }
      calendar.blur();
    });
    pickerWrap.appendChild(calendar);

    const removeButton = createMinusButton('Delete this timestamp column', () => {
      const context = params.context;
      if (context && typeof context.onDeleteColumn === 'function') {
        context.onDeleteColumn(colDef);
      }
    });

    this.gui.appendChild(label);
    this.gui.appendChild(pickerWrap);
    this.gui.appendChild(removeButton);
  }

  getGui() {
    return this.gui;
  }

  refresh() {
    return false;
  }

  destroy() {}
}

class ParameterGroupHeader {
  init(params) {
    this.params = params || {};
    this.parameterName = this.params.displayName || '';
    this.gui = document.createElement('div');
    this.gui.className = 'group-header';

    this.nameLabel = document.createElement('span');
    this.nameLabel.className = 'group-name';
    this.nameLabel.textContent = this.parameterName;
    this.nameLabel.title = 'Double-click to rename this parameter';

    this.nameLabel.addEventListener('dblclick', () => this.startEditing());

    this.gui.appendChild(this.nameLabel);
    this.gui.appendChild(
      createMinusButton('Delete this whole parameter', () => {
        const context = this.params.context;
        if (context && typeof context.onDeleteGroup === 'function') {
          context.onDeleteGroup(this.parameterName);
        }
      })
    );
  }
  startEditing() {
    if (this.gui.querySelector('.group-name-input')) return;
    const originalName = this.parameterName;

    const editor = document.createElement('input');
    editor.type = 'text';
    editor.className = 'group-name-input';
    editor.value = originalName;
    editor.setAttribute('aria-label', 'Rename parameter');

    const commit = () => {
      const newName = editor.value.trim();
      this.finishEditing(editor, originalName);
      if (!newName || newName === originalName) return;
      const context = this.params.context;
      if (context && typeof context.onRenameParameter === 'function') {
        context.onRenameParameter(originalName, newName);
      }
    };

    editor.addEventListener('keydown', (event) => {
      if (event.key === 'Enter') {
        event.preventDefault();
        editor.blur();
      } else if (event.key === 'Escape') {
        editor.value = originalName;
        editor.blur();
      }
    });
    editor.addEventListener('blur', commit);

    this.gui.replaceChild(editor, this.nameLabel);
    editor.focus();
    editor.select();
  }

  finishEditing(editor, nameToShow) {
    if (!editor.parentNode) return;
    this.gui.replaceChild(this.nameLabel, editor);
    this.nameLabel.textContent = nameToShow;
  }

  getGui() {
    return this.gui;
  }

  refresh(newParams) {
    if (newParams && newParams.displayName && newParams.displayName !== this.parameterName) {
      this.parameterName = newParams.displayName;
      this.nameLabel.textContent = this.parameterName;
    }
    return true;
  }

  destroy() {}
}

class RowDeleteRenderer {
  init(params) {
    this.gui = document.createElement('span');
    this.gui.className = 'row-tools';
    this.gui.appendChild(
      createMinusButton('Remove this coordinate row', () => {
        if (!params.node) return;
        onDeleteRow(params.node);
      })
    );
  }

  getGui() {
    return this.gui;
  }

  refresh() {
    return false;
  }

  destroy() {}
}

const ROW_TOOL_COLUMN = {
  headerName: '',
  colId: '__row_tool__',
  pinned: 'left',
  width: 52,
  editable: false,
  sortable: false,
  resizable: false,
  filter: false,
  suppressMovable: true,
  lockPosition: true,
  cellRenderer: 'rowDeleteRenderer',
};

// ---------------------------------------------------------------------------
// Column model builders.
// ---------------------------------------------------------------------------

function makeDateChild(parameterName, iso) {
  return {
    field: `${parameterName}_${iso}`,
    headerName: formatDisplayDate(iso),
    isoDate: iso,
    editable: true,
    minWidth: 120,
    width: 132,
    filter: 'agNumberColumnFilter',
    suppressMovable: true,
    headerComponent: 'dateHeader',
  };
}

function uniqueGroupName(baseName, takenNames) {
  let candidate = baseName;
  let suffix = 2;
  while (takenNames.has(candidate)) {
    candidate = `${baseName} ${suffix}`;
    suffix += 1;
  }
  return candidate;
}

function buildColumnDefs(pivotedData) {
  const isoListsByParameter = new Map();
  if (pivotedData && pivotedData.length > 0) {
    Object.keys(pivotedData[0]).forEach((key) => {
      if (key === 'latitude' || key === 'longitude' || key === 'station_id') return;
      const parts = splitFieldName(key);
      if (!parts) return;
      if (!isoListsByParameter.has(parts.parameter)) isoListsByParameter.set(parts.parameter, []);
      isoListsByParameter.get(parts.parameter).push(parts.iso);
    });
  }

  const groups = [];
  isoListsByParameter.forEach((isoList, parameterName) => {
    const uniqueIsos = [...new Set(isoList)];
    groups.push({
      headerName: parameterName,
      marryChildren: true,
      headerGroupComponent: 'parameterGroupHeader',
      children: uniqueIsos.map((iso) => makeDateChild(parameterName, iso)),
    });
  });

  const totalColumns = () => groups.reduce((total, group) => total + group.children.length, 0);

  if (groups.length > 0) {
    const takenNames = new Set(groups.map((group) => group.headerName));
    const paddingName = uniqueGroupName(PADDING_PARAMETER_NAME, takenNames);
    const paddingGroup = {
      headerName: paddingName,
      marryChildren: true,
      headerGroupComponent: 'parameterGroupHeader',
      children: [],
    };
    while (totalColumns() < GRID_MIN_COLUMNS) {
      paddingGroup.children.push(makeDateChild(paddingName, nextIsoAfter(paddingGroup.children.map((c) => c.isoDate))));
    }
    groups.push(paddingGroup);
  } else {
    const soloGroup = {
      headerName: DEFAULT_PARAMETER_NAME,
      marryChildren: true,
      headerGroupComponent: 'parameterGroupHeader',
      children: [],
    };
    while (soloGroup.children.length < GRID_MIN_COLUMNS) {
      soloGroup.children.push(makeDateChild(DEFAULT_PARAMETER_NAME, nextIsoAfter(soloGroup.children.map((c) => c.isoDate))));
    }
    groups.push(soloGroup);
  }

  groups.forEach((group) => {
    group.children.sort((a, b) => a.isoDate.localeCompare(b.isoDate));
  });

  return [
    { ...ROW_TOOL_COLUMN },
    { field: 'latitude', headerName: 'Latitude', editable: true, pinned: 'left', width: 120 },
    { field: 'longitude', headerName: 'Longitude', editable: true, pinned: 'left', width: 120 },
    ...groups,
  ];
}

// ---------------------------------------------------------------------------
// Context callbacks used by the custom headers.
// ---------------------------------------------------------------------------

async function onDateChange(colDef, newIso, inputElement) {
  const parts = splitFieldName(colDef.field);
  if (!parts) return;
  try {
    const result = await mutateTable('/api/table/rename-timestamp', {
      parameter: parts.parameter,
      old_timestamp: colDef.isoDate,
      new_timestamp: newIso,
      allow_missing: true,
    });
    if (result.moved === 0) {
      relabelDateColumnLocally(colDef.field, parts.parameter, newIso);
      showStatus('Timestamp updated.', 'green');
    }
  } catch (error) {
    showStatus(`Error: ${error.message}`, 'red');
    if (inputElement) inputElement.value = colDef.isoDate || '';
  }
}

async function onDeleteColumn(colDef) {
  const parts = splitFieldName(colDef.field);
  if (!parts) return;
  try {
    const result = await mutateTable('/api/table/delete-series', {
      parameter: parts.parameter,
      timestamp: colDef.isoDate,
    });
    showStatus(`Deleted ${result.deleted ?? 0} measurement(s).`, 'green');
  } catch (error) {
    if (/No matching measurements/i.test(error.message)) {
      removeColumnLocally(colDef.field);
      showStatus('Unsaved column removed.', 'green');
    } else {
      showStatus(`Error: ${error.message}`, 'red');
    }
  }
}

async function onDeleteRow(rowNode) {
  if (!rowNode || !rowNode.data) return;
  const { latitude, longitude, station_id: stationId } = rowNode.data;
  const hasCoordinates = latitude !== undefined && latitude !== null && String(latitude).trim() !== ''
    && longitude !== undefined && longitude !== null && String(longitude).trim() !== '';
  try {
    if (hasCoordinates && stationId !== undefined && stationId !== null) {
      const response = await fetch('/api/table/delete-station', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ latitude, longitude }),
      });
      const result = await response.json().catch(() => ({}));
      if (!response.ok && response.status !== 404) {
        throw new Error(result.detail || result.error || `Request failed (${response.status})`);
      }
    }
    gridOptions.api.applyTransaction({ remove: [rowNode.data] });
    showStatus('Coordinate row deleted.', 'green');
  } catch (error) {
    showStatus(`Error: ${error.message}`, 'red');
  }
}

async function onRenameParameter(oldName, newName, headerInstance) {
  try {
    await mutateTable('/api/table/rename-parameter', { old_name: oldName, new_name: newName });
    showStatus(`Renamed parameter to "${newName}".`, 'green');
  } catch (error) {
    if (/does not exist/i.test(error.message)) {
      renameGroupLocally(oldName, newName);
      showStatus(`Renamed unsaved parameter to "${newName}".`, 'green');
    } else {
      showStatus(`Error: ${error.message}`, 'red');
    }
  }
}

async function onDeleteGroup(parameterName) {
  try {
    const result = await mutateTable('/api/table/delete-series', { parameter: parameterName });
    showStatus(`Deleted ${result.deleted ?? 0} measurement(s).`, 'green');
  } catch (error) {
    if (/No matching measurements/i.test(error.message)) {
      removeGroupLocally(parameterName);
      showStatus('Unsaved parameter removed.', 'green');
    } else {
      showStatus(`Error: ${error.message}`, 'red');
    }
  }
}

function forEachGroup(defs, callback) {
  defs.filter((def) => Array.isArray(def.children)).forEach(callback);
}

function relabelDateColumnLocally(field, parameter, newIso) {
  const defs = gridOptions.api.getColumnDefs();
  forEachGroup(defs, (group) => {
    group.children.forEach((child) => {
      if (child.field !== field) return;
      child.isoDate = newIso;
      child.field = `${parameter}_${newIso}`;
      child.headerName = formatDisplayDate(newIso);
    });
    group.children.sort((a, b) => a.isoDate.localeCompare(b.isoDate));
  });
  gridOptions.api.setColumnDefs(defs);
  gridOptions.api.refreshHeader();
}

function removeColumnLocally(field) {
  const defs = gridOptions.api.getColumnDefs().filter((def) => !def.children);
  forEachGroup(defs, (group) => {
    group.children = group.children.filter((child) => child.field !== field);
  });
  const kept = defs.filter((group) => !group.children || group.children.length > 0);
  gridOptions.api.setColumnDefs(kept);
  gridOptions.api.refreshHeader();
}

function renameGroupLocally(oldName, newName) {
  const defs = gridOptions.api.getColumnDefs();
  forEachGroup(defs, (group) => {
    if (group.headerName !== oldName) return;
    group.headerName = newName;
    group.children.forEach((child) => {
      const parts = splitFieldName(child.field);
      if (parts && parts.parameter === oldName) {
        child.field = `${newName}_${parts.iso}`;
      }
    });
  });
  gridOptions.api.setColumnDefs(defs);
  gridOptions.api.refreshHeader();
}

function removeGroupLocally(parameterName) {
  const staticColumns = gridOptions.api.getColumnDefs().filter((def) => !def.children);
  const remainingGroups = [];
  forEachGroup(gridOptions.api.getColumnDefs(), (group) => {
    if (group.headerName !== parameterName) remainingGroups.push(group);
  });
  gridOptions.api.setColumnDefs([...staticColumns, ...remainingGroups]);
  gridOptions.api.refreshHeader();
}

// ---------------------------------------------------------------------------
// Data loading.
// ---------------------------------------------------------------------------

async function loadAndConfigureGrid() {
  try {
    showStatus('Loading data...', '#0078d4');
    const response = await fetch('/api/table');
    if (!response.ok) throw new Error(`HTTP error! status: ${response.status}`);

    const pivotedData = await response.json();

    const rowData = pivotedData && pivotedData.length > 0 ? [...pivotedData] : [];
    while (rowData.length < GRID_MIN_ROWS) rowData.push({});

    gridOptions.context = { onDateChange, onDeleteColumn, onRenameParameter, onDeleteGroup };
    gridOptions.api.setColumnDefs(buildColumnDefs(pivotedData));
    gridOptions.api.setRowData(rowData);
    showStatus(pivotedData && pivotedData.length > 0 ? `Loaded ${pivotedData.length} records.` : 'Grid ready.', 'green');
  } catch (error) {
    showStatus('Error: ' + (error.message || 'Unknown error'), 'red');
  }
}

// ---------------------------------------------------------------------------
// Toolbar actions (popup-free).
// ---------------------------------------------------------------------------

function addTimestampColumn() {
  const defs = gridOptions.api.getColumnDefs();
  const groups = defs.filter((def) => Array.isArray(def.children));
  if (groups.length === 0) {
    defs.push({
      headerName: DEFAULT_PARAMETER_NAME,
      marryChildren: true,
      headerGroupComponent: 'parameterGroupHeader',
      children: [makeDateChild(DEFAULT_PARAMETER_NAME, todayIso())],
    });
    showStatus('Added the first timestamp column.', 'green');
  } else {
    groups.forEach((group) => {
      const iso = nextIsoAfter(group.children.map((child) => child.isoDate));
      group.children.push(makeDateChild(group.headerName, iso));
      group.children.sort((a, b) => a.isoDate.localeCompare(b.isoDate));
    });
    showStatus(groups.length === 1 ? 'Added a timestamp column.' : 'Added a timestamp column to every parameter.', 'green');
  }
  gridOptions.api.setColumnDefs(defs);
  gridOptions.api.refreshHeader();
}

function addParameterColumn() {
  const defs = gridOptions.api.getColumnDefs();
  const existingNames = defs
    .filter((def) => Array.isArray(def.children))
    .map((group) => group.headerName);
  const name = nextDefaultParameterName(existingNames);
  defs.push({
    headerName: name,
    marryChildren: true,
    headerGroupComponent: 'parameterGroupHeader',
    children: [makeDateChild(name, todayIso())],
  });
  gridOptions.api.setColumnDefs(defs);
  gridOptions.api.refreshHeader();
  showStatus(`Added "${name}" with today's date. Double-click its header to rename.`, 'green');
}

function nextDefaultParameterName(takenNames) {
  const taken = new Set(takenNames);
  let ordinal = 1;
  let candidate = `Parameter ${ordinal}`;
  while (taken.has(candidate)) {
    ordinal += 1;
    candidate = `Parameter ${ordinal}`;
  }
  return candidate;
}

function addCoordinateRow() {
  // Create a new empty row
  const newRow = { latitude: null, longitude: null };
  gridOptions.api.applyTransaction({ add: [newRow] });
  const lastIndex = gridOptions.api.getDisplayedRowCount() - 1;
  if (lastIndex >= 0) {
    gridOptions.api.ensureIndexVisible(lastIndex, 'bottom');
    // Try to focus on the latitude cell of the new row
    setTimeout(() => {
      const lastNode = gridOptions.api.getDisplayedRowAtIndex(lastIndex);
      if (lastNode) {
        gridOptions.api.setFocusedCell(lastIndex, 'latitude');
      }
    }, 50);
  }
  showStatus('Coordinate row added at the bottom.', 'green');
}

// ---------------------------------------------------------------------------
// Saving and status.
// ---------------------------------------------------------------------------

async function saveTableData() {
  showStatus('Validating data...', '#0078d4');

  const rowData = [];
  gridOptions.api.forEachNode(node => rowData.push(node.data));

  const isRowEmpty = (row) => {
    if (!row) return true;
    const keys = Object.keys(row);
    if (keys.length === 0) return true;
    return keys.every(key => row[key] === null || row[key] === undefined || String(row[key]).trim() === '');
  };

  const nonEmptyData = rowData.filter(row => !isRowEmpty(row));

  if (nonEmptyData.length === 0) {
    showStatus('No data to save. The grid is empty.', 'orange');
    return;
  }

  // Validate that all rows have coordinates
  const invalidRows = nonEmptyData.filter(row => {
    const lat = row.latitude;
    const lon = row.longitude;
    return lat == null || String(lat).trim() === '' || lon == null || String(lon).trim() === '';
  });

  if (invalidRows.length > 0) {
    showStatus(`${invalidRows.length} row(s) are missing latitude/longitude and will be skipped.`, 'orange');
  }

  const columnDefs = gridOptions.api.getColumnDefs();
  const unpivotedData = [];

  nonEmptyData.forEach((row) => {
    const latitude = row.latitude;
    const longitude = row.longitude;

    if (latitude == null || String(latitude).trim() === '' || longitude == null || String(longitude).trim() === '') {
      return;
    }

    // Validate coordinates are numeric
    const lat = parseFloat(latitude);
    const lon = parseFloat(longitude);
    if (isNaN(lat) || isNaN(lon)) {
      return;
    }

    columnDefs.forEach(group => {
      if (group.children) {
        const parameter = group.headerName;
        group.children.forEach(child => {
          const timestamp = child.isoDate || child.headerName;
          const value = row[child.field];

          if (value != null && String(value).trim() !== '') {
            // Validate numeric value
            const numValue = parseFloat(value);
            if (!isNaN(numValue)) {
              unpivotedData.push({ latitude, longitude, parameter, timestamp, value: numValue });
            }
          }
        });
      }
    });
  });

  if (unpivotedData.length === 0) {
    showStatus('No valid measurements to save (all data rows were invalid).', 'orange');
    return;
  }

  try {
    showStatus(`Saving ${unpivotedData.length} measurements...`, '#0078d4');
    const response = await fetch('/api/table', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(unpivotedData),
    });

    const result = await response.json();
    if (!response.ok) {
      throw new Error(result.error || result.detail || 'Failed to save data');
    }

    showStatus(`✓ Saved ${unpivotedData.length} measurements successfully! Returning to map...`, 'green');
    // Store the data in session storage for retrieval on main page
    sessionStorage.setItem('trendsmapp_last_dataset', JSON.stringify({
      data: unpivotedData,
      saved_at: new Date().toISOString(),
      message: `Imported ${unpivotedData.length} measurements from data-entry table.`
    }));
    setTimeout(() => { window.location.href = '/'; }, 1500);

  } catch (error) {
    showStatus(`Error: ${error.message}`, 'red');
  }
}

function showStatus(message, color = '#0078d4') {
  const statusEl = document.getElementById('status');
  if (statusEl) {
    statusEl.textContent = message;
    statusEl.style.color = color;

    // Clear all status classes
    statusEl.classList.remove('success', 'error', 'warning', 'info');

    // Apply appropriate class based on color
    if (color === 'green' || color === '#107c10') {
      statusEl.classList.add('success');
    } else if (color === 'red' || color === '#d13438') {
      statusEl.classList.add('error');
    } else if (color === 'orange' || color === '#d83b01') {
      statusEl.classList.add('warning');
    } else {
      statusEl.classList.add('info');
    }

    if (color !== 'red' && color !== 'orange' && color !== '#d13438' && color !== '#d83b01') {
      setTimeout(() => {
        if (statusEl.textContent === message) {
          statusEl.textContent = '';
          statusEl.classList.remove('success', 'error', 'warning', 'info');
        }
      }, 5000);
    }
  }
}

// ---------------------------------------------------------------------------
// Bootstrap.
// ---------------------------------------------------------------------------

function setupEventListeners() {
  const btnAddParam = document.getElementById('btn-add-param');
  const btnAddTimestamp = document.getElementById('btn-add-timestamp');
  const btnAddCoordinate = document.getElementById('btn-add-coordinate');
  const btnSave = document.getElementById('btn-save');
  const btnCancel = document.getElementById('btn-cancel');
  const densityToggle = document.getElementById('density-toggle');

  if (btnAddParam) btnAddParam.addEventListener('click', addParameterColumn);
  if (btnAddTimestamp) btnAddTimestamp.addEventListener('click', addTimestampColumn);
  if (btnAddCoordinate) btnAddCoordinate.addEventListener('click', addCoordinateRow);
  if (btnSave) btnSave.addEventListener('click', saveTableData);
  if (btnCancel) {
    btnCancel.addEventListener('click', () => {
      if (confirm('Are you sure you want to cancel? Any unsaved changes will be lost.')) {
        window.location.href = '/';
      }
    });
  }
  if (densityToggle) {
    // Load saved density preference from localStorage
    const savedDensity = localStorage.getItem('trendsmapp-grid-density') || 'compact';
    densityToggle.value = savedDensity;
    document.body.setAttribute('data-density', savedDensity);
    
    densityToggle.addEventListener('change', (e) => {
      const density = e.target.value;
      localStorage.setItem('trendsmapp-grid-density', density);
      document.body.setAttribute('data-density', density);
    });
  }
}

function initializeGrid() {
  const gridDiv = document.getElementById('data-grid');
  if (!gridDiv) {
    showStatus('Error: Grid container not found.', 'red');
    return;
  }

  gridOptions = {
    context: {},
    components: {
      dateHeader: DateHeader,
      parameterGroupHeader: ParameterGroupHeader,
      rowDeleteRenderer: RowDeleteRenderer,
      dateCellEditor: DateCellEditor,
    },
    defaultColDef: {
      resizable: true,
      sortable: true,
      filter: true,
    },
    columnDefs: [],
    rowData: [],
    suppressMovableColumns: true,
    enableFillHandle: true,
    clipboardDelimiter: '\t',
    onGridReady: (params) => {
      gridOptions.api = params.api;
      loadAndConfigureGrid();
    },
    processCellForClipboard: (params) => params.value,
    processCellFromClipboard: (params) => params.value,
    processDataFromClipboard: (params) => {
        const data = params.data;
        const focusedCell = gridOptions.api.getFocusedCell();
        if (!focusedCell || !data || data.length === 0) {
            return null;
        }

        const startRowIndex = focusedCell.rowIndex;
        const startColId = focusedCell.column.getColId();

        const colDefs = gridOptions.api.getColumnDefs();
        const flatCols = [];

        colDefs.forEach(def => {
            if (def.children) {
                def.children.forEach(child => flatCols.push(child));
            } else {
                flatCols.push(def);
            }
        });

        const startColIndex = flatCols.findIndex(col => col.field === startColId);
        if (startColIndex < 0) return null;

        for (let r = 0; r < data.length; r++) {
            const gridRow = gridOptions.api.getDisplayedRowAtIndex(startRowIndex + r);
            if (!gridRow) continue;

            const updatedRow = { ...gridRow.data };
            for (let c = 0; c < data[r].length; c++) {
                const colDef = flatCols[startColIndex + c];
                if (colDef && colDef.field && colDef.editable !== false) {
                    updatedRow[colDef.field] = data[r][c];
                }
            }

            gridOptions.api.applyTransaction({ update: [updatedRow] });
        }

        return null;
    },
  };

  new agGrid.Grid(gridDiv, gridOptions);
}

if (typeof agGrid === 'undefined') {
  showStatus('Error: AG Grid library failed to load.', 'red');
} else {
  initializeGrid();
  setupEventListeners();
}
*/
