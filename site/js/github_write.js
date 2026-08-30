// Confirma a execucao de um alerta diretamente do navegador, escrevendo um
// evento em data/events.jsonl via GitHub Contents API. O workflow
// on_execute.yml (disparado por esse push) reconcilia a carteira ficticia.
//
// O token e um GitHub fine-grained PAT, com acesso restrito a este unico
// repositorio e permissao so de "Contents: Read and write", colado pelo
// proprio usuario e guardado so no localStorage deste navegador - nunca sai
// daqui para nenhum outro servico.

const GH_OWNER = "alefonsecabb";
const GH_REPO = "Negociador";
const GH_BRANCH = "main";
const GH_EVENTS_PATH = "data/events.jsonl";
const GH_TOKEN_STORAGE_KEY = "negociador_gh_pat";

function ghGetToken() {
  try {
    return localStorage.getItem(GH_TOKEN_STORAGE_KEY) || "";
  } catch {
    return "";
  }
}

function ghSetToken(token) {
  try {
    if (token) localStorage.setItem(GH_TOKEN_STORAGE_KEY, token);
    else localStorage.removeItem(GH_TOKEN_STORAGE_KEY);
  } catch {
    // localStorage indisponivel (aba privada, etc.) - a confirmacao via navegador
    // simplesmente nao funcionara; o fallback local (CLI + git push) continua valendo.
  }
}

function b64EncodeUnicode(str) {
  return btoa(unescape(encodeURIComponent(str)));
}

function b64DecodeUnicode(str) {
  return decodeURIComponent(escape(atob(str)));
}

async function ghAppendEvent(alertId, fillPrice) {
  const token = ghGetToken();
  if (!token) {
    throw new Error("Nenhum token do GitHub configurado. Cole um fine-grained PAT na secao 'Confirmar execucao pelo navegador'.");
  }
  const apiBase = `https://api.github.com/repos/${GH_OWNER}/${GH_REPO}/contents/${GH_EVENTS_PATH}`;
  const headers = {
    Authorization: `Bearer ${token}`,
    Accept: "application/vnd.github+json",
  };

  let sha = null;
  let existingContent = "";
  const getResp = await fetch(`${apiBase}?ref=${GH_BRANCH}`, { headers });
  if (getResp.status === 200) {
    const data = await getResp.json();
    sha = data.sha;
    existingContent = b64DecodeUnicode(data.content.replace(/\n/g, ""));
  } else if (getResp.status !== 404) {
    throw new Error(`Falha ao ler ${GH_EVENTS_PATH}: HTTP ${getResp.status}`);
  }

  const event = { alert_id: alertId, fill_price: fillPrice ?? null, recorded_at: new Date().toISOString() };
  const newContent = existingContent + JSON.stringify(event) + "\n";

  const putResp = await fetch(apiBase, {
    method: "PUT",
    headers: { ...headers, "Content-Type": "application/json" },
    body: JSON.stringify({
      message: `Confirma execucao do alerta #${alertId}`,
      content: b64EncodeUnicode(newContent),
      branch: GH_BRANCH,
      ...(sha ? { sha } : {}),
    }),
  });
  if (!putResp.ok) {
    const body = await putResp.text();
    throw new Error(`Falha ao gravar evento: HTTP ${putResp.status} - ${body}`);
  }
  return true;
}
