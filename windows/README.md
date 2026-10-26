ToastFX for Windows - tiny proof (mic -> effect -> VB-Cable)

1) Install Python 3.11 or newer from python.org. On the first screen tick "Add python.exe to PATH".
2) Open Command Prompt and run:   pip install sounddevice numpy scipy
3) Install VB-Cable (free) from vb-audio.com/Cable : unzip, right-click VBCABLE_Setup_x64.exe, Run as administrator, then restart Windows.
4) Put the files from this zip in a folder, open Command Prompt there and run:
      python toastfx_proof.py --list     (check you can see "CABLE Input")
      python toastfx_proof.py            (starts with Helmet)
5) In Discord: Settings > Voice & Video > Input Device = "CABLE Output (VB-Audio Virtual Cable)". Turn Automatic Gain Control off.
6) Talk. Keys in the Command Prompt window: d = dry, r = radio, h = helmet, [ and ] = effect strength, q = quit.

Tell me: what the Latency line says, whether the cpu number stays low, whether "dropouts" climbs, and how it sounds in Discord's mic test.
If your headset isn't the Windows default mic, add:  --mic "part of its name"
If you get crackling, try:  python toastfx_proof.py --block 512
