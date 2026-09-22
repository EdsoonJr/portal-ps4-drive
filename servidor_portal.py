import os
import json
import time
import requests
from fastapi import FastAPI, HTTPException, Request, Header
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from typing import Optional
from google.auth.transport.requests import Request as GoogleAuthRequest
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(BASE_DIR)

# IDs do Google Drive
ID_PASTA_INBOX = os.getenv("ID_PASTA_INBOX", "1d8tsBGeZ-sfBqK1JDRh9nF-WzIs_0-s0")
ID_PASTA_JOGOS = os.getenv("ID_PASTA_JOGOS", "1zAaCdRq884zpkbLyB28_yDf7RA7JVxaJ")

# Senha da comunidade (padrão local caso não definida na nuvem)
SENHA_PORTAL = os.getenv("SENHA_PORTAL", "ps4brasil")

SCOPES = ['https://www.googleapis.com/auth/drive']
app = FastAPI()

CACHE_JOGOS = {"timestamp": 0, "dados": []}

def obter_credenciais():
    """Lê as credenciais da variável de ambiente TOKEN_JSON ou dos arquivos locais."""
    token_env = os.getenv("TOKEN_JSON")
    creds = None
    
    if token_env:
        try:
            token_dict = json.loads(token_env)
            creds = Credentials.from_authorized_user_info(token_dict, SCOPES)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Erro ao ler TOKEN_JSON da variável de ambiente: {e}")
    else:
        # Fallback local
        caminho_token = os.path.join(ROOT_DIR, 'token.json') if os.path.exists(os.path.join(ROOT_DIR, 'token.json')) else os.path.join(BASE_DIR, 'token.json')
        if os.path.exists(caminho_token):
            creds = Credentials.from_authorized_user_file(caminho_token, SCOPES)

    if not creds:
        raise HTTPException(status_code=500, detail="Credenciais do Google Drive não configuradas.")

    if creds.expired and creds.refresh_token:
        creds.refresh(GoogleAuthRequest())

    return creds

class SolicitacaoUpload(BaseModel):
    nome: str
    tamanho: int

@app.get("/", response_class=HTMLResponse)
def pagina_inicial():
    html_path = os.path.join(BASE_DIR, "templates", "index.html")
    with open(html_path, "r", encoding="utf-8") as f:
        return f.read()

@app.post("/api/iniciar-upload")
def iniciar_upload(dados: SolicitacaoUpload, req: Request, x_senha: Optional[str] = Header(None)):
    # Validação da senha da comunidade
    if x_senha != SENHA_PORTAL:
        raise HTTPException(status_code=401, detail="Senha de acesso incorreta.")

    creds = obter_credenciais()
    token = creds.token
    
    origem = req.headers.get("origin") or "http://127.0.0.1:8000"
    url_google = "https://www.googleapis.com/upload/drive/v3/files?uploadType=resumable"
    
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json; charset=UTF-8",
        "X-Upload-Content-Type": "application/octet-stream",
        "X-Upload-Content-Length": str(dados.tamanho),
        "Origin": origem
    }
    
    metadata = {
        "name": dados.nome,
        "parents": [ID_PASTA_INBOX]
    }
    
    res = requests.post(url_google, headers=headers, json=metadata)
    if res.status_code == 200:
        return {"uploadUrl": res.headers.get("Location")}
    else:
        raise HTTPException(status_code=res.status_code, detail=f"Erro Google: {res.text}")

@app.get("/api/jogos")
def listar_jogos():
    agora = time.time()
    if agora - CACHE_JOGOS["timestamp"] < 60 and CACHE_JOGOS["dados"]:
        return {"jogos": CACHE_JOGOS["dados"]}

    creds = obter_credenciais()
    drive = build('drive', 'v3', credentials=creds)

    query = f"mimeType = 'application/vnd.google-apps.folder' and '{ID_PASTA_JOGOS}' in parents and trashed = false"
    resultado = drive.files().list(
        q=query,
        fields="files(id, name, webViewLink)",
        pageSize=100,
        orderBy="name"
    ).execute()

    pastas = resultado.get('files', [])
    jogos = []

    for pasta in pastas:
        nome_completo = pasta['name']
        cusa = ""
        titulo = nome_completo

        if "[" in nome_completo and "]" in nome_completo:
            partes = nome_completo.rsplit("[", 1)
            titulo = partes[0].strip()
            cusa = partes[1].replace("]", "").strip()

        jogos.append({
            "id": pasta['id'],
            "nomeCompleto": nome_completo,
            "titulo": titulo,
            "cusa": cusa,
            "link": pasta.get('webViewLink', f"https://drive.google.com/drive/folders/{pasta['id']}")
        })

    CACHE_JOGOS["timestamp"] = agora
    CACHE_JOGOS["dados"] = jogos
    return {"jogos": jogos}

if __name__ == "__main__":
    import uvicorn
    porta = int(os.getenv("PORT", 8000))
    uvicorn.run("servidor_portal:app", host="0.0.0.0", port=porta, reload=False)