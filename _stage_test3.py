import requests, time, glob
B = "http://127.0.0.1:8010"
f = glob.glob("app/static/uploads/*SU_SOG*")[0]
print("FILE:", f, flush=True)
with open(f, "rb") as fh:
    up = requests.post(f"{B}/api/upload-drawing", files={"file": fh}, timeout=60).json()
print("UPLOAD:", up.get("file_url"), flush=True)
r = requests.post(f"{B}/api/engineering-loop/start", json={
    "initial_eval": up, "user_answers": {"thickness": "4.0", "material": "St37-2"},
    "upload_name": up.get("file_name"), "file_url": up.get("file_url")}, timeout=60).json()
sid = r.get("session_id")
print("START session:", sid, flush=True)
for i in range(12):
    d = requests.post(f"{B}/api/engineering-loop/iterate", json={"session_id": sid}, timeout=200).json()
    st = d.get("state", {})
    v = st.get("classification") or {}
    cls = v.get("classification") if isinstance(v, dict) else v
    print(f"ITER {i+1}: stage={st.get('stage')} status={st.get('status')} cls={cls} done={d.get('done')} err={d.get('error')}", flush=True)
    if d.get("done") or d.get("error"):
        break
    time.sleep(0.5)
