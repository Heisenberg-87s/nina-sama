import asyncio
import pyvts

async def get_params():
    vts = pyvts.vts(plugin_info={"plugin_name": "Nina-sama", "developer": "Heisenberg", "authentication_token_path": "vts_token.txt"})
    await vts.connect()
    await vts.read_token()
    await vts.authenticate()
    
    msg = {
        "apiName": "VTubeStudioPublicAPI",
        "apiVersion": "1.0",
        "requestID": "ParamQuery",
        "messageType": "InputParameterListRequest"
    }
    resp = await vts.request(msg)
    
    print("Default:")
    for p in resp['data'].get('defaultParameters', []):
        if 'Brow' in p['name'] or 'Smile' in p['name']:
            print(p['name'])
            
    print("Custom:")
    for p in resp['data'].get('customParameters', []):
        if 'Brow' in p['name'] or 'Smile' in p['name']:
            print(p['name'])
            
    await vts.close()

asyncio.run(get_params())
