import network
import socket
import machine
from pins import D8, D10, GPKEY
import time
import _thread

# Wi-Fi Access Point (AP Mode)
ap = network.WLAN(network.AP_IF)
ap.active(True)
ap.config(essid="ESP32_Control", password="12345678")

print("Booting AP...")
while not ap.active():
    print(".", end="")
    time.sleep(0.05)

print("AP Config:", ap.ifconfig())
print("Access Point Active. Connect to 'ESP32_Control'")
print("Server running at http://192.168.4.1/")

# Hardware Setup
buzzer = machine.PWM(D10, machine.Pin.OUT)
buzzer.freq(1000)
buzzer.duty_u16(0)

# Physical disarm button (active LOW)
SWITCH = machine.Pin(GPKEY, machine.Pin.IN, machine.Pin.PULL_UP)
BTN = machine.Pin(D8, machine.Pin.IN, machine.Pin.PULL_UP)

# Global State
armed = False
flat_tone = False
cnt = False
do_beep = True
current_delay = "Disarmed"

# Physical button state tracking
arm_progress = 0.0
arm_holding = False
last_btn_state = SWITCH.value()
arming_started = False

# Disarm State
disarm_enabled = False
disarm_progress = 0.0
disarm_active = False

# --- Utility Functions ---
def beep():
    if do_beep:
        buzzer.duty_u16(2700)
        time.sleep(0.05)
        buzzer.duty_u16(0)

def start_beep():
    for _ in range(3):
        buzzer.duty_u16(2700)
        time.sleep(0.3)
        buzzer.duty_u16(0)
        time.sleep(0.1)

def flat_line(set_frq=False):
    global flat_tone
    buzzer.freq(500 if set_frq else 1000)
    buzzer.duty_u16(2700)
    flat_tone = True

# --- Bomb Countdown Logic ---
def bomb():
    global cnt, current_delay, armed
    cnt = True

    total_time = 45
    start_interval = 1.0
    end_interval = 0.05

    start_beep()
    start_time = time.time()

    while cnt:
        elapsed = time.time() - start_time
        remaining = total_time - elapsed
        if remaining <= 0:
            break

        interval = max(end_interval, start_interval - ((start_interval - end_interval) * (elapsed / total_time)))
        current_delay = f"{remaining:.1f} sec left"
        print(f"\rRemaining: {current_delay}", end='')

        beep()
        time.sleep(interval)

    if cnt:
        print("\nFlat tone!")
        flat_line(set_frq=True)
        current_delay = "Flat Tone!"
    armed = False
    cnt = False

# --- Physical Button Handling ---
def button_thread():
    global armed, cnt, arm_progress, arm_holding, last_btn_state, disarm_enabled, arming_started, allow_arm_control
    
    while True:
        btn_state = SWITCH.value()
        
        if not cnt:
            # Button pressed (active LOW)
            if not btn_state and last_btn_state:
                # Button just pressed
                arm_holding = True
                arm_progress = 0.0
                if not armed and not cnt:
                    arming_started = True
                    print("Button pressed - arming started")
                    beep()  # Start beep
            
            # Button released
            elif btn_state and not last_btn_state:
                # Button just released
                if arm_holding:
                    # If we were holding for arming but released before completion
                    if arm_progress < 4.0 and not armed:
                        print("Arming canceled")
                        beep(); time.sleep(0.1); beep()
                
                arm_holding = False
                arm_progress = 0.0
                arming_started = False
            
            # Button is being held
            if not btn_state and arm_holding:
                arm_progress += 0.1
                
                # Arm after holding for 4 seconds
                if not armed and arm_progress >= 4.0:
                    armed = True
                    arm_holding = False
                    arming_started = False
                    print("Bomb Armed!")
                    beep(); time.sleep(0.1); beep(); time.sleep(0.1); beep()
        
        # Update disarm enabled state
        disarm_enabled = cnt and not btn_state  # True if countdown running and button held
        allow_arm_control = not btn_state
        
        last_btn_state = btn_state
        time.sleep(0.1)

_thread.start_new_thread(button_thread, ())

# --- Web Hold Logic ---
def disarm_progress_thread():
    global disarm_progress, disarm_active, cnt, current_delay, armed, do_beep

    while True:
        if cnt and disarm_enabled:
            if disarm_active:
                disarm_progress += 0.05
                if disarm_progress >= 3.5:
                    buzzer.freq(1500)   # a little bit higher pitch
                else:
                    buzzer.freq(1000)
                buzzer.duty_u16(2500)
                time.sleep(0.03)
                buzzer.duty_u16(0)
                buzzer.freq(1000)
                if disarm_progress >= 7:
                    print("\nBomb disarmed!")
                    # Reset everything
                    disarm_progress = 0
                    disarm_active = False
                    cnt = False
                    armed = False
                    current_delay = "Disarmed"
                    
                    beep(); time.sleep(0.05); beep()
                    flat_line()
                    time.sleep(0.5)
                    buzzer.duty_u16(0)
            else:
                # Reset progress if web button not held
                do_beep = True
                disarm_progress = 3.5 if disarm_progress >= 3.5 else 0 if disarm_progress > 0 else disarm_progress
        else:
            disarm_progress = 0 if not cnt else 3.5 if disarm_progress >= 3.5 else 0
            disarm_active = False

        time.sleep(0.02)

_thread.start_new_thread(disarm_progress_thread, ())

# --- HTTP Server ---
def start_server():
    while True:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind(("0.0.0.0", 80))
            s.listen(5)

            while True:
                conn, addr = s.accept()
                request = conn.recv(1024).decode()
                response = handle_request(request)
                conn.send(response)
                conn.close()
        except OSError as e:
            print("Server error:", e)
            try: s.close()
            except: pass
            time.sleep(1)

def handle_request(request):
    global armed, cnt, current_delay, disarm_active, disarm_enabled, disarm_progress, arm_progress, arming_started, flat_tone, do_beep, allow_arm_control
    if "/hold_start" in request and disarm_enabled:
        disarm_active = True
        do_beep = False
        return b"HTTP/1.1 200 OK\r\n\r\nStarted"
    elif "/hold_stop" in request:
        disarm_active = False
        do_beep = True
        return b"HTTP/1.1 200 OK\r\n\r\nStopped"
    elif "/progress" in request:
        return f"HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\n\r\n{7 - disarm_progress:.2f}".encode()
    elif "/armprogress" in request:
        return f"HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\n\r\n{arm_progress:.1f}".encode()
    elif "/reset" in request and not cnt and flat_tone:
        armed = False
        cnt = False
        flat_tone = False
        current_delay = "Disarmed"
        buzzer.freq(1000)
        do_beep = True
        beep()
        return b"HTTP/1.1 200 OK\r\n\r\nReset"
    elif "/showreset" in request:
        data = "YES" if not cnt and flat_tone else "NO"
        return f"HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\n\r\n{data}".encode()
    elif "/activate" in request and armed and not cnt:
        print("Bomb Activated via web!")
        _thread.start_new_thread(bomb, ())
        return b"HTTP/1.1 200 OK\r\n\r\nActivated"
    elif "/disarm" in request and armed and not cnt:
        armed = False
        print("Bomb Disarmed via web!")
        beep(); time.sleep(0.1); beep(); time.sleep(0.1); beep(); time.sleep(0.1); beep()
        return b"HTTP/1.1 200 OK\r\n\r\nDisarmed"
    elif "/status" in request:
        status = "Armed" if armed else "Disarmed"
        if cnt:
            status += " - Countdown Running"
        return f"HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\n\r\n{status}".encode()
    elif "/statdisarm" in request:
        status = "SHOW_DISARM" if disarm_enabled else ""
        return f"HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\n\r\n{status}".encode()
    elif "/delay" in request:
        return f"HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\n\r\n{current_delay}".encode()
    elif "/hidedelay" in request:
        data = "NO" if cnt else "YES"
        return f"HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\n\r\n{data}".encode()
    elif "/armingstatus" in request:
        status = "ARMING" if (arming_started and not cnt and not armed) else "NOT"
        return f"HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\n\r\n{status}".encode()
    elif "/buttoninstructions" in request:
        if cnt:
            instructions = ""
        elif armed and not allow_arm_control:
            instructions = "Use the buttons below"
        elif arming_started:
            instructions = "Arming in progress..."
        elif allow_arm_control and armed:
            instructions = "Turn switch off and remove key"
        else:
            instructions = "Turn the switch to arm"
        return f"HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\n\r\n{instructions}".encode()
    elif "/armedstatus" in request:
        status = "ARMED" if (armed and not cnt and not allow_arm_control) else "NOT"
        return f"HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\n\r\n{status}".encode()
    return (b"HTTP/1.1 200 OK\r\nContent-Type: text/html\r\n\r\n" + generate_html().encode())

def generate_html():
    global disarm_enabled
    if disarm_enabled:
        page = """\
<!DOCTYPE html>
<html>
<head>
<title>Disarm the Bomb</title>
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<style>
/* For mobile devices */
@media only screen and (max-width: 600px) {
    body { font-size: 18px; }
    #hold { padding: 30px; font-size: 28px; }
    #delay, #prog { font-size: 24px; }
    .disarm-progress-bar { 
        width: 90%; 
        height: 40px; 
    }
}
.disarm-progress-bar { 
    width: 300px; 
    height: 30px; 
    border: 2px solid #333; 
    margin: 10px auto; 
    background-color: #f0f0f0; 
}
.disarm-progress-fill { 
    height: 100%; 
    background-color: #4CAF50; 
    width: 0%; 
    transition: width 0.1s;
}
</style>
</head>
<body style="font-family:Arial; text-align:center;">
<h1 style="color:red;">Bomb Active!</h1>
<p>Hold the button below while keeping the disarm switch on!</p>
<p id="delay">Remaining: {}</p>
<button id="hold" style="padding:20px; font-size:22px;"
    onmousedown="startHold()" onmouseup="stopHold()"
    ontouchstart="startHold()" ontouchend="stopHold()">Hold to Disarm</button>
<div class="disarm-progress-bar">
    <div id="disarmBar" class="disarm-progress-fill"></div>
</div>
<p id="prog">Progress: <span id="disarmTime">{}</span>s remaining</p>

<script>
let interval=null;

function startHold(){ fetch('/hold_start'); interval = setInterval(updateProgress, 200); }
function stopHold(){ fetch('/hold_stop'); clearInterval(interval); }

function updateProgress(){ 
    fetch('/progress').then(r=>r.text()).then(d=>{ 
        document.getElementById('disarmTime').innerText = d;
        let progressPercent = Math.min(100, ((7 - d) / 7) * 100);
        document.getElementById('disarmBar').style.width = progressPercent + '%';
    });
    fetch('/delay').then(r=>r.text()).then(d=>{ document.getElementById('delay').innerText = "Remaining: " + d; });
}

setInterval(()=>{ fetch('/statdisarm').then(r=>r.text()).then(data=>{ if(!data.includes("SHOW_DISARM")){ setTimeout(() => { location.reload(); }, 1000); }; }); }, 500);

setInterval(updateProgress, 500);
</script>
</body>
</html>
"""
    else:
        page = """\
<!DOCTYPE html>
<html>
<head>
<title>ESP32 Control Panel</title>
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<style>
body { font-family: Arial; text-align: center; justify-content: center; align-items: center;}
.btn { padding: 15px; font-size: 20px; margin: 5px; }
#status { font-size: 24px; font-weight: bold; margin-top: 20px; }
#delay { font-size: 20px; font-weight: bold; color: red; margin-top: 10px; }
#instructions { font-size: 18px; margin: 15px 0; color: #555; }
.progress-bar { 
    width: 300px; 
    height: 30px; 
    border: 2px solid #333; 
    margin: 10px auto; 
    background-color: #f0f0f0; 
    display: none;
}
.progress-fill { 
    height: 100%; 
    background-color: #4CAF50; 
    width: 0%; 
    transition: width 0.1s;
}
.armed-controls { 
    display: none; 
    margin: 15px 0;
}
/* For mobile devices */
@media only screen and (max-width: 600px) {
    body { font-size: 18px; }
    .btn { padding: 20px; font-size: 24px; }
    #status { font-size: 28px; }
    #delay { font-size: 24px; }
    #instructions { font-size: 22px; }
    .progress-bar { 
        width: 90%; 
        height: 40px; 
    }
}
</style>
</head>
<body>
<h1>Bomb Control</h1>

<div id="rst">
<button class="btn" onclick="sendCommand('/reset')">RESET</button>
</div>
<p id="disarm">Turn the disarm switch to enable the disarm page</p>
<p id="status">Disarmed</p>
<p id="delay">Remaining: {}</p>
<p id="instructions"></p>

<div id="armedControls" class="armed-controls">
    <button class="btn" style="background-color: #4CAF50;" onclick="sendCommand('/activate')">ACTIVATE</button>
    <button class="btn" style="background-color: #f44336;" onclick="sendCommand('/disarm')">DISARM</button>
</div>

<div id="armingProgress" class="progress-bar">
    <div id="armingBar" class="progress-fill"></div>
</div>
<p id="armingText" style="display: none;">Keep switch on: <span id="armingTime">0.0</span>s / 4.0s</p>

<script>
function sendCommand(url){ fetch(url).then(updateStatus); }
function updateStatus(){ 
    fetch('/status').then(r=>r.text()).then(d=>{
        document.getElementById('status').innerText = d;
        // Update status color based on state
        if(d.includes("Armed")) {
            document.getElementById('status').style.color = "orange";
            if(d.includes("-")) {
                document.getElementById('status').style.color = "red";
            }
        } else {
            document.getElementById('status').style.color = "green";
        }
    });
    fetch('/delay').then(r=>r.text()).then(d=>document.getElementById('delay').innerText="Remaining: "+d);
    
    // Update button instructions
    fetch('/buttoninstructions').then(r=>r.text()).then(instructions=>{
        document.getElementById('instructions').innerText = instructions;
    });
    
    // Check armed status to show/hide controls
    fetch('/armedstatus').then(r=>r.text()).then(data=>{
        if(data.includes("ARMED")) {
            document.getElementById('armedControls').style.display = 'block';
        } else {
            document.getElementById('armedControls').style.display = 'none';
        }
    });
    
    fetch('/showreset').then(r=>r.text()).then(data=>{
        if(data.includes("YES")) {
            document.getElementById('rst').style.display = 'block';
        } else {
            document.getElementById('rst').style.display = 'none';
        }
    });
    
    fetch('/hidedelay').then(r=>r.text()).then(data=>{
        if(data.includes("NO")) {
            document.getElementById('delay').style.display = 'block';
            document.getElementById('disarm').style.display = 'block';
        } else {
            document.getElementById('delay').style.display = 'none';
            document.getElementById('disarm').style.display = 'none';
        }
    });
    
    // Check arming status (only show if not in countdown and not armed)
    fetch('/armingstatus').then(r=>r.text()).then(data=>{
        if(data.includes("ARMING") && !document.getElementById('status').innerText.includes("Armed")) {
            document.getElementById('armingProgress').style.display = 'block';
            document.getElementById('armingText').style.display = 'block';
            fetch('/armprogress').then(r=>r.text()).then(progress=>{
                let progressPercent = Math.min(100, (progress / 4.0) * 100);
                document.getElementById('armingBar').style.width = progressPercent + '%';
                document.getElementById('armingTime').innerText = progress;
            });
        } else {
            document.getElementById('armingProgress').style.display = 'none';
            document.getElementById('armingText').style.display = 'none';
        }
    });
}

// Update status immediately on page load
updateStatus();

setInterval(()=>{ fetch('/statdisarm').then(r=>r.text()).then(data=>{ if(data.includes("SHOW_DISARM")){ setTimeout(() => { location.reload(); }, 1000); }; }); }, 500);

setInterval(updateStatus, 200);
</script>
</body>
</html>
"""
    return page

_thread.start_new_thread(start_server, ())

# Keep main program alive
while True:
    time.sleep(1)
