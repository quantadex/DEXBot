make build
docker build -t dexbot .
docker tag dexbot quantalabs/dexbot:latest
docker push quantalabs/dexbot:latest