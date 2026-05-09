import React, { useState } from 'react';
import axios from 'axios';
import './App.css';

const api = axios.create({
  baseURL: 'http://localhost:5000',
  withCredentials: true,  // needed for flask session
});

function App() {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [database, setDatabase] = useState('');

  const [connected, setConnected] = useState(false);
  const [dbSummary, setDbSummary] = useState(null);
  const [query, setQuery] = useState('');
  const [response, setResponse] = useState(null);
  const [loading, setLoading] = useState(false);
  const [connectLoading, setConnectLoading] = useState(false);
  const [connectError, setConnectError] = useState(null);
  const [currentStage, setCurrentStage] = useState('');

  const [schemaInfo, setSchemaInfo] = useState(null);
  const [schemaLoading, setSchemaLoading] = useState(false);
  const [showSchemaInfo, setShowSchemaInfo] = useState(false);

  const handleConnect = async () => {
    setConnectLoading(true);
    setConnectError(null);
    setDbSummary(null);
    setConnected(false);

    try {
      const res = await api.post('/connect', { username, password, database });
      setDbSummary(res.data.summary);  // updated: was res.data
      setConnected(true);
    } catch (err) {
      setConnectError(err.response?.data?.error || 'Failed to connect');
    }

    setConnectLoading(false);
  };

  const handleAsk = async () => {
    if (!query.trim()) return;

    setLoading(true);
    setResponse(null);
    setCurrentStage('Selecting relevant tables...');

    try {
      setCurrentStage('Planning query...');
      const res = await api.post('/query', { query });
      setResponse(res.data);
    } catch (err) {
      if (err.response?.status === 401) {
        setConnected(false);
        setResponse({ error: 'Session expired. Please reconnect.' });
      } else {
        setResponse({ error: err.response?.data?.error || 'Error talking to backend' });
      }
    }

    setCurrentStage('');
    setLoading(false);
  };

  const handleRefreshSchema = async () => {
    try {
      const res = await api.post('/refresh-schema');
      setDbSummary(res.data.summary);
      alert('Schema refreshed!');
    } catch (err) {
      alert('Failed to refresh schema.');
    }
  };

  const handleDisconnect = async () => {
    await api.post('/disconnect');
    setConnected(false);
    setDbSummary(null);
    setResponse(null);
    setQuery('');
    setUsername('');
    setPassword('');
    setDatabase('');
    setSchemaInfo(null);
    setShowSchemaInfo(false);
  };

  const handleSchemaInfo = async () => {
  setSchemaLoading(true);
  setShowSchemaInfo(true);
  setSchemaInfo(null);
  try {
    const res = await api.get('/schema-info');
    setSchemaInfo(res.data);
  } catch (err) {
    alert('Failed to fetch schema info.');
  }
  setSchemaLoading(false);
  };


  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !loading && query.trim()) {
      handleAsk();
    }
  };

  return (
    <div className="App" style={{ maxWidth: 750, margin: 'auto', padding: 20 }}>
      <h1>🗄️ Talk to Your Database</h1>

      {/* ── CONNECT FORM ── */}
      {!connected && (
        <div style={{ marginBottom: 20 }}>
          <h3>Connect to your database</h3>
          <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
            <input
              type="text"
              placeholder="Username"
              value={username}
              onChange={e => setUsername(e.target.value)}
            />
            <input
              type="password"
              placeholder="Password"
              value={password}
              onChange={e => setPassword(e.target.value)}
            />
            <input
              type="text"
              placeholder="Database name"
              value={database}
              onChange={e => setDatabase(e.target.value)}
            />
            <button
              onClick={handleConnect}
              disabled={connectLoading || !username || !database}
            >
              {connectLoading ? 'Connecting...' : 'Connect'}
            </button>
          </div>
          {connectError && (
            <p style={{ color: 'red', marginTop: 10 }}>{connectError}</p>
          )}
        </div>
      )}

      {/* ── DB SUMMARY TABLE ── */}
      {connected && dbSummary && (
        <div style={{ marginBottom: 20 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <h3>📋 Schema</h3>
            <div style={{ display: 'flex', gap: 10 }}>
              <button onClick={handleRefreshSchema} style={{ fontSize: 12 }}>
                🔄 Refresh Schema
              </button>
              <button onClick={handleSchemaInfo} style={{ fontSize: 12, color: '#555' }}>
                🔍 Explain Schema
              </button>
              <button onClick={handleDisconnect} style={{ fontSize: 12, color: 'red' }}>
                Disconnect
              </button>
            </div>
          </div>
          <table border="1" cellPadding="8" style={{ borderCollapse: 'collapse', width: '100%' }}>
            <thead>
              <tr style={{ background: '#f0f0f0' }}>
                <th>Table</th>
                <th>Columns</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(dbSummary).map(([table, columns]) => (
                <tr key={table}>
                  <td><b>{table}</b></td>
                  <td style={{ fontSize: 13, color: '#444' }}>{columns.join(', ')}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <hr />
          {showSchemaInfo && (
  <div style={{ marginBottom: 20 }}>
    <div style={{ display: 'flex', justifyContent: 'space-between' }}>
      <h3>🧩 Schema Details</h3>
      <button onClick={() => setShowSchemaInfo(false)} style={{ fontSize: 12 }}>
        ✕ Close
      </button>
    </div>

    {schemaLoading && (
      <p style={{ color: '#888', fontStyle: 'italic' }}>⏳ Analyzing schema...</p>
    )}

    {schemaInfo && !schemaLoading && (
      <>
        {/* Plain English Explanation */}
        <div style={{ background: '#f9f9e8', padding: 10, borderRadius: 6, marginBottom: 12 }}>
          <h4>📖 What this database contains</h4>
          <p style={{ fontSize: 14, whiteSpace: 'pre-wrap', color: '#444' }}>
            {schemaInfo.explanation}
          </p>
        </div>

        {/* Relationships */}
        {schemaInfo.relationships && schemaInfo.relationships.length > 0 && (
          <div style={{ background: '#f0f4ff', padding: 10, borderRadius: 6, marginBottom: 12 }}>
            <h4>🔗 Table Relationships</h4>
            <table border="1" cellPadding="8" style={{ borderCollapse: 'collapse', width: '100%', fontSize: 13 }}>
              <thead>
                <tr style={{ background: '#f0f0f0' }}>
                  <th>From Table</th>
                  <th>Column</th>
                  <th>→</th>
                  <th>To Table</th>
                  <th>Column</th>
                  <th>Type</th>
                  <th>Meaning</th>
                </tr>
              </thead>
              <tbody>
                {schemaInfo.relationships.map((rel, i) => (
                  <tr key={i}>
                    <td><b>{rel.from_table}</b></td>
                    <td style={{ color: '#666' }}>{rel.from_column}</td>
                    <td style={{ textAlign: 'center' }}>→</td>
                    <td><b>{rel.to_table}</b></td>
                    <td style={{ color: '#666' }}>{rel.to_column}</td>
                    <td style={{ color: '#888', fontSize: 12 }}>{rel.type}</td>
                    <td style={{ color: '#555', fontStyle: 'italic', fontSize: 12 }}>{rel.label}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {schemaInfo.relationships && schemaInfo.relationships.length === 0 && (
          <p style={{ color: '#888', fontSize: 14 }}>No relationships detected between tables.</p>
        )}
      </>
    )}
    <hr />
  </div>
)}
        </div>
      )}

      {/* ── QUERY INPUT ── */}
      {connected && (
        <div style={{ display: 'flex', gap: 10, marginBottom: 10 }}>
          <input
            type="text"
            placeholder="e.g. Show all students from CSE department"
            value={query}
            onChange={e => setQuery(e.target.value)}
            onKeyDown={handleKeyDown}
            style={{ flex: 1 }}
          />
          <button onClick={handleAsk} disabled={loading || !query.trim()}>
            {loading ? 'Thinking...' : 'Ask'}
          </button>
        </div>
      )}

      {/* ── LOADING STAGE INDICATOR ── */}
      {loading && currentStage && (
        <p style={{ color: '#888', fontStyle: 'italic' }}>⏳ {currentStage}</p>
      )}

      {/* ── RESPONSE ── */}
      {response && (
        <div className="result" style={{ marginTop: 20 }}>

          {response.error && (
            <div style={{ background: '#fff0f0', padding: 10, borderRadius: 6, color: 'red' }}>
              ❌ {response.error}
              {response.details && (
                <pre style={{ fontSize: 12, marginTop: 8, color: '#555' }}>{response.details}</pre>
              )}
            </div>
          )}

          {response.plan && (
            <div style={{ background: '#f9f9e8', padding: 10, borderRadius: 6, marginBottom: 10 }}>
              <h4>🧠 Query Plan</h4>
              <p style={{ whiteSpace: 'pre-wrap', fontSize: 14 }}>{response.plan}</p>
            </div>
          )}

          {response.sql && (
            <div style={{ background: '#f0f4ff', padding: 10, borderRadius: 6, marginBottom: 10 }}>
              <h4>🔍 Generated SQL</h4>
              <pre style={{ overflowX: 'auto' }}>{response.sql}</pre>
              {response.sql_explanation && (
                <p style={{ fontSize: 14, color: '#444', marginTop: 6 }}>
                  💬 {response.sql_explanation}
                </p>
              )}
            </div>
          )}

          {response.result && (
            <div style={{ marginBottom: 10 }}>
              <h4>📊 Result ({response.result.length} rows)</h4>

              {response.result.length === 0 ? (
                <p style={{ color: '#888' }}>No results found.</p>
              ) : (
                <div style={{ overflowX: 'auto' }}>
                  <table border="1" cellPadding="8" style={{ borderCollapse: 'collapse', width: '100%', fontSize: 13 }}>
                    <thead>
                      <tr style={{ background: '#f0f0f0' }}>
                        {Object.keys(response.result[0]).map(col => (
                          <th key={col}>{col}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {response.result.map((row, i) => (
                        <tr key={i}>
                          {Object.values(row).map((val, j) => (
                            <td key={j}>{String(val)}</td>
                          ))}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}

              {response.result_explanation && (
                <p style={{ fontSize: 14, color: '#444', marginTop: 8 }}>
                  💬 {response.result_explanation}
                </p>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export default App;