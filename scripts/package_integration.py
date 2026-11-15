"""Build and verify the backend and Person 5 handoff archives."""
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED
import hashlib

root=Path(__file__).resolve().parents[1]
skip={'__pycache__','.pytest_cache','.venv','.uv-cache','.git','node_modules','dist'}
def files_under(folder):
    return [p for p in (root/folder).rglob('*') if p.is_file() and not any(x in skip for x in p.relative_to(root).parts)]
backend=[]
for folder in ('agents','orchestration','tools','optimization','schemas','api','tests','examples','scripts','original_modules','frontend_client','FRONTEND_DATA_EXAMPLES'):
    backend+=files_under(folder)
backend += [root/x for x in ('README.md','ARCHITECTURE.md','API_CONTRACT.md','API_REFERENCE.md',
    'FRONTEND_INTEGRATION_GUIDE.md','INTEGRATION_REPORT.md','TEST_REPORT.md','PROJECT_STATUS.md',
    'NEXT_MEMBER_START_HERE.md','requirements.txt','.env.example','openapi.json')]
handoff=[]
for folder in ('FRONTEND_DATA_EXAMPLES','frontend_client'):
    handoff+=files_under(folder)
for folder in ('original_modules/person3/moon_navigation/src/web',
               'original_modules/person3/moon_navigation/src/shared',
               'original_modules/person3/moon_navigation/fixtures'):
    handoff+=files_under(folder)
handoff += [root/'original_modules/person3/moon_navigation'/x for x in
            ('package.json','package-lock.json','vite.config.ts','tsconfig.json','API_CONTRACT.md','NEXT_MEMBER_START_HERE.md')]
handoff += [root/x for x in ('FRONTEND_INTEGRATION_GUIDE.md','API_REFERENCE.md','API_CONTRACT.md',
    'openapi.json','ARCHITECTURE.md','INTEGRATION_REPORT.md','TEST_REPORT.md','README.md')]
for name,files in [('LUNA_NAV_AI_INTEGRATED_BACKEND.zip',backend),('LUNA_NAV_AI_PERSON_5_HANDOFF.zip',handoff)]:
    target=root/name
    with ZipFile(target,'w',ZIP_DEFLATED) as archive:
        for p in sorted(files): archive.write(p,p.relative_to(root).as_posix())
    with ZipFile(target) as archive:
        assert archive.testzip() is None
        assert set(archive.namelist())=={p.relative_to(root).as_posix() for p in files}
        for p in files:
            assert hashlib.sha256(archive.read(p.relative_to(root).as_posix())).digest()==hashlib.sha256(p.read_bytes()).digest()
    print(name,len(files),'files',target.stat().st_size,'bytes VERIFIED')
