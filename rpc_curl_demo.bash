# Delete:
curl http://127.0.0.1:5000/rpc/reviews?id=2996 -X DELETE -v

# Create:
curl http://127.0.0.1:5000/rpc/reviews -d "content=something new" -X POST -v

