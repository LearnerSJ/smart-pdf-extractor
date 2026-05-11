/**
 * Export extraction results to CSV or Excel format.
 */

export function exportToCSV(result, filename) {
  const rows = [];
  const output = result.output || result;
  
  // Metadata row
  rows.push(['Document ID', output.doc_id || '']);
  rows.push(['Schema Type', output.schema_type || '']);
  rows.push(['Status', output.status || '']);
  rows.push([]);
  
  // Fields
  rows.push(['--- EXTRACTED FIELDS ---']);
  rows.push(['Field', 'Value', 'Confidence', 'Source']);
  const fields = output.fields || {};
  for (const [name, field] of Object.entries(fields)) {
    if (name === 'accounts') continue; // Handle separately
    const val = typeof field === 'object' ? (field.value ?? '') : field;
    const conf = typeof field === 'object' ? (field.confidence ?? '') : '';
    const src = typeof field === 'object' ? (field.provenance?.source ?? '') : '';
    rows.push([name, String(val), String(conf), src]);
  }
  rows.push([]);
  
  // Transactions from accounts
  const accounts = fields.accounts?.value || fields.accounts || [];
  if (Array.isArray(accounts)) {
    for (const acct of accounts) {
      if (!acct || typeof acct !== 'object') continue;
      rows.push([`--- ACCOUNT: ${acct.account_number || acct.iban || 'Unknown'} ---`]);
      rows.push(['Opening Balance', acct.opening_balance ?? '']);
      rows.push(['Closing Balance', acct.closing_balance ?? '']);
      rows.push([]);
      
      // Tables within account
      const tables = acct.tables || [];
      for (const table of tables) {
        if (!table || !table.headers) continue;
        rows.push([`Table: ${table.table_type || 'transactions'}`]);
        rows.push(table.headers);
        for (const row of (table.rows || [])) {
          if (Array.isArray(row)) {
            rows.push(row.map(String));
          } else if (typeof row === 'object') {
            rows.push(table.headers.map(h => String(row[h] ?? '')));
          }
        }
        rows.push([]);
      }
    }
  }
  
  // Convert to CSV string
  const csv = rows.map(row => 
    Array.isArray(row) ? row.map(cell => `"${String(cell).replace(/"/g, '""')}"`).join(',') : `"${row}"`
  ).join('\n');
  
  // Download
  const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = `${filename || 'extraction'}.csv`;
  link.click();
  URL.revokeObjectURL(url);
}

export function exportToExcel(result, filename) {
  // For Excel, we generate a simple HTML table that Excel can open
  const output = result.output || result;
  let html = '<html><head><meta charset="utf-8"></head><body>';
  
  // Sheet 1: Metadata
  html += '<h2>Metadata</h2><table border="1">';
  html += `<tr><td>Document ID</td><td>${output.doc_id || ''}</td></tr>`;
  html += `<tr><td>Schema Type</td><td>${output.schema_type || ''}</td></tr>`;
  html += `<tr><td>Status</td><td>${output.status || ''}</td></tr>`;
  
  const fields = output.fields || {};
  for (const [name, field] of Object.entries(fields)) {
    if (name === 'accounts') continue;
    const val = typeof field === 'object' ? (field.value ?? '') : field;
    html += `<tr><td>${name}</td><td>${val}</td></tr>`;
  }
  html += '</table>';
  
  // Sheet 2: Transactions
  const accounts = fields.accounts?.value || fields.accounts || [];
  if (Array.isArray(accounts)) {
    for (const acct of accounts) {
      if (!acct || typeof acct !== 'object') continue;
      const tables = acct.tables || [];
      for (const table of tables) {
        if (!table || !table.headers) continue;
        html += `<h2>${table.table_type || 'Transactions'} - ${acct.account_number || ''}</h2>`;
        html += '<table border="1"><tr>';
        for (const h of table.headers) html += `<th>${h}</th>`;
        html += '</tr>';
        for (const row of (table.rows || [])) {
          html += '<tr>';
          if (Array.isArray(row)) {
            for (const cell of row) html += `<td>${cell ?? ''}</td>`;
          } else if (typeof row === 'object') {
            for (const h of table.headers) html += `<td>${row[h] ?? ''}</td>`;
          }
          html += '</tr>';
        }
        html += '</table>';
      }
    }
  }
  
  html += '</body></html>';
  
  const blob = new Blob([html], { type: 'application/vnd.ms-excel' });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = `${filename || 'extraction'}.xls`;
  link.click();
  URL.revokeObjectURL(url);
}
