# Autogen-Portainer-Agent
A custom Autogen agent for working with a local Portainer instance.

Follow the instructions [here](https://microsoft.github.io/autogen/docs/installation/Docker) to setup an autogen container environment.

Run this script in your container with a command like: ```docker run -it -e OPENAI_API_KEY=YourAPIKeyHere -v $(pwd)/Autogen-Portainer-Agent:/home/autogen/Autogen-Portainer-Agent autogen_base_img:latest python /home/autogen/Autogen-Portainer-Agent/agent.py "Analyze the logs for the container named portainer_agent"```
