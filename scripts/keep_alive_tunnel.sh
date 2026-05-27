#!/bin/bash
echo "Starting robust self-healing localtunnel script..."

PORT=8002
SUBDOMAIN="penner-policy-api"
EXPECTED_URL="https://${SUBDOMAIN}.loca.lt"
LOG_FILE="/tmp/lt_connection.log"

while true; do
  # Kill any existing localtunnel processes for port 8002
  EXISTING_PIDS=$(pgrep -f "lt.*--port $PORT|localtunnel.*--port $PORT")
  if [ -n "$EXISTING_PIDS" ]; then
    echo "Killing existing localtunnel processes: $EXISTING_PIDS"
    kill $EXISTING_PIDS > /dev/null 2>&1
    sleep 3
  fi
  
  echo "Connecting localtunnel to port $PORT on subdomain $SUBDOMAIN..."
  rm -f $LOG_FILE
  ./node_modules/.bin/lt --port $PORT --subdomain $SUBDOMAIN --local-host 127.0.0.1 > $LOG_FILE 2>&1 &
  
  # Wait for URL to be generated (up to 15 seconds)
  GENERATED_URL=""
  for i in {1..45}; do
    sleep 1
    GENERATED_URL=$(grep -o -E "https://[a-zA-Z0-9.-]+" $LOG_FILE | head -n 1)
    if [ -n "$GENERATED_URL" ]; then
      break
    fi
  done
  echo "Generated URL: $GENERATED_URL"
  
  if [ "$GENERATED_URL" != "$EXPECTED_URL" ]; then
    echo "Warning: Did not get expected subdomain (got $GENERATED_URL instead of $EXPECTED_URL)."
    echo "Retrying in 60 seconds..."
    sleep 60
    continue
  fi
  
  echo "Successfully established tunnel on expected subdomain: $EXPECTED_URL"
  
  # Enter health check loop
  while true; do
    sleep 30
    
    # 1. Check if localtunnel process is still running
    LT_PID=$(pgrep -f "lt.*--port $PORT|localtunnel.*--port $PORT")
    if [ -z "$LT_PID" ]; then
      echo "localtunnel process died. Restarting..."
      break
    fi
    
    # 2. Check if the connection log has recorded any error
    if grep -E -q "error|failed|connection refused|lost connection" $LOG_FILE; then
      echo "localtunnel log contains errors. Restarting..."
      break
    fi
    
    # 3. Check if public backend tunnel is warm and healthy (with retry)
    PUBLIC_STATUS=$(curl -s -m 15 -H "Bypass-Tunnel-Reminder: true" -o /dev/null -w "%{http_code}" "https://${SUBDOMAIN}.loca.lt/api/v1/suggestions/home")
    if [ "$PUBLIC_STATUS" != "200" ]; then
      echo "Warning: Public tunnel returned HTTP $PUBLIC_STATUS. Retrying in 5 seconds..."
      sleep 5
      PUBLIC_STATUS=$(curl -s -m 15 -H "Bypass-Tunnel-Reminder: true" -o /dev/null -w "%{http_code}" "https://${SUBDOMAIN}.loca.lt/api/v1/suggestions/home")
      if [ "$PUBLIC_STATUS" != "200" ]; then
        echo "Public tunnel is consistently unhealthy (HTTP Status: $PUBLIC_STATUS). Restarting localtunnel..."
        break
      fi
    fi
    
    echo "Tunnel process is active and healthy."
  done
done
