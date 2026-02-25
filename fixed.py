lines = open('config.py', encoding='utf-8').readlines()
out = []
for l in lines:
    if 'LOCALAITV_LOCATION_ID' in l:
        out.append('LOCALAITV_LOCATION_ID = 1\n')
    elif 'LOCALAITV_CATEGORY_ID' in l:
        out.append('LOCALAITV_CATEGORY_ID = 2\n')
    else:
        out.append(l)
open('config.py', 'w', encoding='utf-8').writelines(out)
print('Fixed! Testing...')
import importlib.util
spec = importlib.util.spec_from_file_location("config", "config.py")
mod = importlib.util.load_from_spec(spec)
spec.loader.exec_module(mod)
print(f'LOCALAITV_LOCATION_ID = {mod.LOCALAITV_LOCATION_ID}')
print('OK - now run: python runner.py')