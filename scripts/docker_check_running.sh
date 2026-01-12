
if docker ps --format "{{.Image}}" | grep -q "hololink-demo:2.3.1"; then
    echo "✅ Docker container with hololink-demo:2.3.1 is running."
    exit 0
else
    echo "❌ Container not found."
    exit 1
fi

'
