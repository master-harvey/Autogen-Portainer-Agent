import autogen
from typing_extensions import Annotated, Literal
from typing import Optional, Dict, Union, Callable, List
from os import environ, remove
from json import dumps
import requests
import tempfile

class PortainerAgent(autogen.agentchat.AssistantAgent):
    DEFAULT_SYSTEM_MESSAGE = "You are an AI assistant that can retrieve information about the local portainer instance one endpoint at a time. "
    "One portainer instance may manage multiple docker endpoints/environments, if an endpoint/environment is required but the user does not specify "
    "the endpoint/environment id you will need to either have them specify by name or id, or if they don't or cannot specify then check all available "
    "endpoints/environments. Do your best to generate a response to the user's request by using the tools and functions available to you. "
    "Once the task is complete, or if a function encounters an error, or if it seems like a function result didn't return "
    "enough data to make a decision, then MAKE ABSOLUTELY SURE that the LAST WORD of your reply is: TERMINATE\n"
    "If the conversation is over, instead of asking what else you can help with simply reply with one word: TERMINATE"

    def __init__(
            self, user_proxy, connection: Dict, name: str,
            system_message: Optional[str] = None,
            llm_config: Optional[Union[Dict, Literal[False]]] = None,
            is_termination_msg: Optional[Callable[[Dict], bool]] = None,
            max_consecutive_auto_reply: Optional[int] = None,
            human_input_mode: Optional[str] = "NEVER",
            description: Optional[str] = None,
            **kwargs
        ):
        self.user_proxy = user_proxy

        super().__init__(
            name,
            system_message if system_message else PortainerAgent.DEFAULT_SYSTEM_MESSAGE,
            llm_config,
            is_termination_msg,
            max_consecutive_auto_reply,
            human_input_mode,
            description,
            **kwargs
        )

        @self.user_proxy.register_for_execution()
        @self.register_for_llm(description="List all endpoints/environments that this portainer instance manages")
        def list_endpoints() -> str:
            api_endpoint = f"{connection['url']}/endpoints"
            headers = {"X-API-Key":connection['token']}

            try:
                response = requests.get(api_endpoint, headers=headers)
                response.encoding = response.apparent_encoding
                response.raise_for_status()  # Raise an exception for non-200 status codes

                # Parse and filter the JSON response
                endpoint_info = response.json()

                if len(endpoint_info) == 0:
                    reply = f"No endpoints are managed by this portainer instance."
                else:
                    # Create a new list with filtered attributes for each container
                    filtered_endpoint_info = []
                    for endpoint in endpoint_info:
                        filtered_endpoint_info.append("Endpoint Id: "+str(endpoint.get("Id", ""))+"\nName: "+endpoint.get("Name", "")+"\nPublicURL: "+endpoint.get("PublicURL", "")+"\nStatus: "+str(endpoint.get("Status", "")))
                    
                    return "<Managed Endpoints>\n" + "\n---\n".join(filtered_endpoint_info) + "\n<End Managed Endoints>"

            except Exception as e:
                return f"Error retrieving info on endpoints. | Encountered error:\n{e}"


        @self.user_proxy.register_for_execution()
        @self.register_for_llm(description="Get info on all the containers running on an endpoint")
        def list_containers(
            endpoint_id: Annotated[int, "The short numerical ID of the endpoint/environment"]
        ) -> str:
            api_endpoint = f"{connection['url']}/endpoints/{endpoint_id}/docker/containers/json"
            headers = {"X-API-Key":connection['token']}

            try:
                response = requests.get(api_endpoint, headers=headers)
                response.encoding = response.apparent_encoding
                response.raise_for_status()  # Raise an exception for non-200 status codes

                # Parse and filter the JSON response
                container_info = response.json()

                if len(container_info) == 0:
                    return f"No containers are running currently"
                else:
                    # Create a new list with filtered attributes for each container
                    filtered_container_info = []
                    for container in container_info:
                        filtered_container_info.append("Container Id: "+container.get("Id", "")+"\nName(s): "+" | ".join([name[1:] for name in container.get("Names", [])])+"\nImage: "+container.get("Image", "")+"\nState: "+container.get("State", "")+"\nCreated at: "+str(container.get("Created","")))
                    
                    return f"<Info on containers running on endpoint {endpoint_id}>\n" + "\n---\n".join(filtered_container_info) + f"\n<End Info on containers running on endpoint {endpoint_id}>"

            except Exception as e:
                return f"Error retrieving container info on endpoint <{endpoint_id}> | Encountered error:\n{e}"

        @self.user_proxy.register_for_execution()
        @self.register_for_llm(description="Get a single container's logs using it's id, and optionally limit the search to a number of lines, and/or via a timestamp window.")
        def get_container_logs(
            container_id: Annotated[str, "The 64-character container id of which to retrieve logs"],
            endpoint_id: Annotated[int, "The short numerical ID of the endpoint/environment"],
            since: Annotated[int, "Retrieve all logs with a unix timestamp greater than this value"]=0,
            until: Annotated[int, "Retrieve all logs with a unix timestamp less than this value"]=0,
            tail: Annotated[int, "Limit the total number of log lines retrieved"]=20,
        ) -> str:
            api_endpoint = f"{connection['url']}/endpoints/{endpoint_id}/docker/containers/{container_id}/logs"
            headers = {"X-API-Key":connection['token']}

            if until and not since:
                    raise ValueError("'since' must be provided if 'until' is specified")
            if not since and not tail:
                raise ValueError("Either 'since' or 'tail' must be provided")

            if tail < 10: #always summarize at least 10 lines
                tail = 10

            params = { "since":since, "until":until, "tail":tail, "stderr": True, "stdout": True, "timestamps": True }
            try:
                response = requests.get(api_endpoint, headers=headers, params=params)
                response.encoding = response.apparent_encoding
                response.raise_for_status()  # Raise an exception for non-200 status codes

                lines = response.text.splitlines()
                if len(lines) <= tail:
                  logs = response.text
                else:
                  logs = "\n".join(lines[-tail:])

                return f"<logs for container_id: {container_id}>\n{logs}\n<end logs for container>"

            except Exception as e:
                return f"Error retrieving logs for <{container_id}> | Encountered Error:\n{e}"
            
        @self.user_proxy.register_for_execution()
        @self.register_for_llm(description="Create a new container from an image name")
        def create_container(
            endpoint_id: Annotated[int, "The short numerical ID of the endpoint/environment"],
            image: Annotated[str, "The container image to run"],
            name: Annotated[str, "A descriptive name to give the container"],
            env: Annotated[Dict, "Container environment variables supplied as a dictionary"] = None,
            labels: Annotated[Dict, "Container labels supplied as a dictionary"] = None,
            ports: Annotated[Dict, "Dictionary where keys define exposed container ports and values are their mapping to the host's port"] = None,
            command: Annotated[str, "Run this command in the container Ex. 'python3 /home/user/main.py'"] = None
        ) -> str:
            api_endpoint = f"{connection['url']}/endpoints/{endpoint_id}/docker/container/create"
            headers = {"X-API-Key":connection['token']}
            params = {name:name}

            try:
                body = {
                    "Image": image,
                    "Labels": labels if labels is not None else {},
                    "Cmd": command.strip().split(" ") if command is not None else "", #split into the list docker likes
                    "Env": [f"{e}={env[e]}" for e in env] if env is not None else [] #dict to list of KEY=VAL
                }
                if(ports): #weird docker api syntax Ex: 22/tcp expose ports on tcp and udp
                    body['ExposedPorts'] = {
                        **{f"{port}/tcp":{} for port in ports},
                        **{f"{port}/udp":{} for port in ports}
                    }

                    body['HostConfig'] = { #map all exposed ports, deploy container as a stack if only exposing a port is necessary
                        "PortBindings": {
                            **{f"{port}/tcp":[{"HostPort":f"{ports[port]}"}] for port in ports},
                            **{f"{port}/udp":[{"HostPort":f"{ports[port]}"}] for port in ports}
                        }
                    }
                
                response = requests.post(api_endpoint, headers=headers, params=params, body=body)
                response.encoding = response.apparent_encoding
                response.raise_for_status()  # Raise an exception for non-200 status codes

                # Parse and filter the JSON response
                container_info = response.json()
                
                return f"{image} container started with Id: {container_info.Id}"

            except Exception as e:
                return f"Error starting container. | Encountered error:\n{e}"

        @self.user_proxy.register_for_execution()
        @self.register_for_llm(description="Start, Stop, Restart, Pause, Unpause, or Kill a container")
        def set_conatainer_state(
            endpoint_id: Annotated[int, "The short numerical ID of the endpoint/environment"],
            container_id: Annotated[str, "The 64-character container id of which to retrieve logs"],
            state: Annotated[str, "One of: 'Start', 'Stop', 'Restart', 'Pause', 'Unpause', or 'Kill'"]
        ) -> str:
            api_endpoint = f"{connection['url']}/endpoints/{endpoint_id}/docker/containers/{container_id}/{state.lower()}"
            headers = {"X-API-Key":connection['token']}

            try:
                response = requests.post(api_endpoint, headers=headers)
                response.encoding = response.apparent_encoding
                response.raise_for_status()  # Raise an exception for non-200 status codes
                return f"{state.upper()} container <{container_id}>: success"

            except Exception as e:
                return f"Error {state.lower()}ing container. | Encountered error:\n{e}"
            
        @self.user_proxy.register_for_execution()
        @self.register_for_llm(description="Kill the process if necessary and Remove the container from memory")
        def remove_container(
            endpoint_id: Annotated[int, "The short numerical ID of the endpoint/environment"],
            container_id: Annotated[str, "The 64-character container id of which to retrieve logs"]
        ) -> str:
            api_endpoint = f"{connection['url']}/endpoints/{endpoint_id}/docker/containers/{container_id}/remove"
            headers = {"X-API-Key":connection['token']}

            params = {'v':False,'force':False} #don't remove anonymous volumes | don't force kill the container
            try:
                response = requests.delete(api_endpoint, headers=headers, params=params)
                response.encoding = response.apparent_encoding
                response.raise_for_status()  # Raise an exception for non-200 status codes
                return f"Container removed successfully: <{container_id}>"

            except Exception as e:
                return f"Error removing container <{container_id}>. | Encountered error:\n{e}"
            

        @self.user_proxy.register_for_execution()
        @self.register_for_llm(description="List the images stored on this endpoint")
        def list_images(
            endpoint_id: Annotated[int, "The short numerical ID of the endpoint/environment"]
        ) -> str:
            api_endpoint = f"{connection['url']}/endpoints/{endpoint_id}/docker/images"
            headers = {"X-API-Key":connection['token']}

            try:
                response = requests.get(api_endpoint, headers=headers)
                response.encoding = response.apparent_encoding
                response.raise_for_status()  # Raise an exception for non-200 status codes

                # Parse and filter the JSON response
                images_info = response.json()

                if len(images_info) == 0:
                    return f"No images are stored on endpoint {endpoint_id}"
                else:
                    # Create a new list with filtered attributes for each image
                    filtered_image_info = []
                    for image in images_info:
                        filtered_image_info.append("Tag(s): "+" | ".join([tag for tag in image.get("RepoTags", [])])+"\Size: "+str(image.get("Size",""))+"\nCreated: "+str(image.get("Created","")))
                    
                    return f"<Images on Endpoint {endpoint_id}>\n" + "\n---\n".join(filtered_image_info) + f"\n<End Images on Endpoint {endpoint_id}>"

            except Exception as e:
                return f"Error retrieving images from endpoint {endpoint_id}. | Encountered error:\n{e}"
        
        #DON'T EXECUTE OTHER PEOPLE'S CODE THIS EASILY JUST YET
        # @self.user_proxy.register_for_execution()
        # @self.register_for_llm(description="Search container images")
        # def search_images(
        #     endpoint_id: Annotated[int, "The short numerical ID of the endpoint/environment"],
        #     search_term: Annotated[str, "The term to search on Docker Hub"]
        # ) -> str:
        #     api_endpoint = f"{connection['url']}/endpoints/images/search"
        #     headers = {"X-API-Key":connection['token']}

        #     try:
        #         response = requests.get(api_endpoint, headers=headers)
        #         response.encoding = response.apparent_encoding
        #         response.raise_for_status()  # Raise an exception for non-200 status codes

        #         # Parse and filter the JSON response
        #         endpoint_info = response.json()
                
        #         return "<Managed Example> <End Managed Example>"

        #     except Exception as e:
        #         return f"Error retrieving info on example. | Encountered error:\n{e}"
            
        #I don't actually think there is any use for this, just specify an image when creating a stack or container
        # @self.user_proxy.register_for_execution() 
        # @self.register_for_llm(description="Pull an image from a remote repository")
        # def pull_image(
        #     endpoint_id: Annotated[int, "The short numerical ID of the endpoint/environment"],
        #     search_term: Annotated[str, "The "]
        # ) -> str:
            api_endpoint = f"{connection['url']}/endpoints"
            headers = {"X-API-Key":connection['token']}

            try:
                response = requests.get(api_endpoint, headers=headers)
                response.encoding = response.apparent_encoding
                response.raise_for_status()  # Raise an exception for non-200 status codes

                # Parse and filter the JSON response
                endpoint_info = response.json()
                
                return "<Managed Example> <End Managed Example>"

            except Exception as e:
                return f"Error retrieving info on example. | Encountered error:\n{e}"
            
        @self.user_proxy.register_for_execution()
        @self.register_for_llm(description="Build an image from a remote Dockerfile")
        def build_image( # Must specify source by Git URL
            endpoint_id: Annotated[int, "The short numerical ID of the endpoint/environment"],
            source: Annotated[str, "The URL to a git hosted Dockerfile or tarball archive with a Dockerfile in the root of the archive"],
            nametag: Annotated[str, "A name and tag to give the image in the standard name:tag format"],
            labels: Annotated[Dict, "Optional dictionary of labels to apply to the image"] = {}
        ) -> str:
            api_endpoint = f"{connection['url']}/endpoints/{endpoint_id}/docker/images/build"
            headers = {"X-API-Key":connection['token']}

            params = { "remote": source, "t": nametag, "labels": dumps(labels) }
            try:
                response = requests.post(api_endpoint, headers=headers, params=params)
                response.encoding = response.apparent_encoding
                response.raise_for_status()  # Raise an exception for non-200 status codes
                
                return f"Successfully built image: {nametag}"

            except Exception as e:
                return f"Error building image {nametag}. | Encountered error:\n{e}"
            

        @self.user_proxy.register_for_execution()
        @self.register_for_llm(description="List the stacks running on this endpoint")
        def list_stacks(
            endpoint_id: Annotated[int, "The short numerical ID of the endpoint/environment"]
        ) -> str:
            api_endpoint = f"{connection['url']}/stacks"
            headers = {"X-API-Key":connection['token']}

            params = { "filters": { "EndpointID": endpoint_id } }
            try:
                response = requests.get(api_endpoint, headers=headers, params=params)
                response.encoding = response.apparent_encoding
                response.raise_for_status() # Raise an exception for non-200 status codes

                stacks_info = response.json() # Parse and filter the JSON response

                if len(stacks_info) == 0:
                    return f"No stacks on endpoint {endpoint_id}"
                else:
                    # Create a new list with filtered attributes for each stack
                    stack_types = {1: "Swarm", 2:"Compose", 3:"Kubernetes"}
                    stack_type_names = { 1: "Swarm", 2:"Stack", 3:"Cluster" }
                    filtered_stack_info = []
                    for stack in stacks_info:
                        stack_info = stack_type_names[stack.get("Type","")]+" Name: "+stack.get("Name", "")+"\nId: "+stack.get("Id", "")+"\nStatus: "+stack.get("Status", "")+"\nType: "+stack_types[stack.get("Type","")]+"\nCreated: "+stack.get("Created", "")
                        if(stack.get("Type","") == 1):
                            stack_info += "\nSwarm Id: "+stack.get("SwarmId", "")
                        filtered_stack_info.append()
                    
                    return f"<Stacks on endpoint {endpoint_id}>\n" + "\n---\n".join(filtered_stack_info) + f"\n<End Stacks on endpoint {endpoint_id}>"

            except Exception as e:
                return f"Error retrieving stacks on endpoint {endpoint_id}. | Encountered error:\n{e}"
            
        @self.user_proxy.register_for_execution()
        @self.register_for_llm(description="Get the file that defines a stack")
        def get_stack_file(
            stack_id: Annotated[str, "The short numerical ID of the stack"]
        ) -> str:
            api_endpoint = f"{connection['url']}/stacks/{stack_id}/file"
            headers = {"X-API-Key":connection['token']}

            try:
                response = requests.get(api_endpoint, headers=headers)
                response.encoding = response.apparent_encoding
                response.raise_for_status()  #Raise an exception for non-200 status codes
                content = response.json()["StackFileContent"]
                
                return f"<File for stack {stack_id}>\n{content}\n<End File for stack {stack_id}>"

            except Exception as e:
                return f"Error retrieving file for stack {stack_id}. | Encountered error:\n{e}"
            
        @self.user_proxy.register_for_execution()
        @self.register_for_llm(description="Create a new stack")
        def create_stack( #### FINISH THIS ####
            endpoint_id: Annotated[int, "The short numerical ID of the endpoint/environment"],
            name: Annotated[str, "A short and descriptive name for the stack"],
            source: Annotated[str, "Source of the stack definition. Either a URL to a public repository with a compose file at the root of the repo, a URL to the compose file itself, or the contents of the stack file"],
            # type: Annotated[int, "The type of stack, one of: 'Swarm', 'Compose', or 'Kubernetes'"] = "Compose",
            env: Annotated[Dict, "Optional dictionary of environment variables for the stack, ignored when deploying with kubernetes"] = {}
        ) -> str:
            # stack_types = {"swarm": 1, "compose": 2, "kubernetes": 3}

            api_endpoint = f"{connection['url']}/stacks/create/standalone"
            headers = {"X-API-Key":connection['token']}

            try:
                params = { "endpointId":endpoint_id }

                if source.startswith("http"): #Remote source
                    #if there's a file extension assume it's a file, else repo
                    if("." in source[-5:]): 
                        api_endpoint += "/file" #download the file and supply it as form-data

                        # Check file size and type
                        head_response = requests.head(source)
                        head_response.raise_for_status()

                        # Get file size
                        file_size = int(head_response.headers.get("Content-Length", 0))

                        # Validate size and type (adjust criteria as needed)
                        if file_size > 100 * 1024:  # Check if file is larger than 100kB, that'd be a huge compose file
                            raise ValueError("Input file too large")

                        # Download the file using temporary file
                        with tempfile.NamedTemporaryFile(delete=False) as temp_file:
                            response = requests.get(source)
                            response.raise_for_status()
                            temp_file.write(response.content)
                        
                        # deploy the stack
                        response = requests.post(api_endpoint, headers=headers, params=params, data={"Name":name, "Env":dumps(env)}, files={"file": open(temp_file.name, "rb")})

                        #delete tempFile
                        remove(temp_file.name)

                    else:
                        #just supply the repo url
                        api_endpoint += "/repository"

                        body = {
                            "name": name,
                            "repositoryURL": source,
                            "repositoryAuthentication": False,
                            "env": [{"name":e, "value":env[e]} for e in env]
                        }

                        response = requests.post(api_endpoint, headers=headers, params=params, body=body)
                    
                else: #Supplied directly as string
                    api_endpoint += "/string"

                    body = {
                        "name": name,
                        "stackFileContent": source,
                        "env": [{"name":e, "value":env[e]} for e in env]
                    }

                    response = requests.post(api_endpoint, headers=headers, params=params, body=body)

                response.encoding = response.apparent_encoding
                response.raise_for_status()  # Raise an exception for non-200 status codes
                stack_info = response.json()
                
                return f"Created stack {stack_info.Name} successfully with stack id <{stack_info.Id}>"

            except Exception as e:
                return f"Error retrieving info on example. | Encountered error:\n{e}"
            
        @self.user_proxy.register_for_execution()
        @self.register_for_llm(description="Start or stop a stack")
        def set_stack_state(
            stack_id: Annotated[str, "The id of the stack to start or stop"],
            state: Annotated[bool, "True to start the stack or False to stop it"]
        ) -> str:
            action = "start" if state else "stop"
            api_endpoint = f"{connection['url']}/stacks/{stack_id}/{action}"
            headers = {"X-API-Key":connection['token']}

            try:
                response = requests.post(api_endpoint, headers=headers)
                response.encoding = response.apparent_encoding
                response.raise_for_status()  # Raise an exception for non-200 status codes
                
                return f"{action} stack <{stack_id}>: Successful"

            except Exception as e:
                return f"Error {action}ing stack {stack_id}. | Encountered error:\n{e}"
            
        @self.user_proxy.register_for_execution()
        @self.register_for_llm(description="Start or stop a stack")
        def update_stack(
            endpoint_id: Annotated[int, "The short numerical ID of the endpoint/environment"],
            stack_id: Annotated[str, "The id of the stack to start or stop"],
            file_contents: Annotated[str, "Optional updated stack file contents"] = "",
            env: Annotated[Dict, "Optional dictionary of environment variables for the stack"] = {}
        ) -> str:
            api_endpoint = f"{connection['url']}/stacks/{stack_id}"
            headers = {"X-API-Key":connection['token']}
            body = {}

            try:
                if(len(env) > 0):
                    body["Env"] = [{"name":e, "value":env[e]} for e in env]
                
                if(file_contents):
                    body["stackFileContent"] = file_contents

                params = {"endpointId":endpoint_id}

                response = requests.put(api_endpoint, headers=headers, params=params, body=body)
                response.encoding = response.apparent_encoding
                response.raise_for_status()  # Raise an exception for non-200 status codes
                
                return f"Updated stack {stack_id} successful"

            except Exception as e:
                return f"Error updating stack {stack_id}. | Encountered error:\n{e}"


# Example function usage
if __name__ == "__main__":
    llm_config = {
        "timeout": 120,
        "config_list": [
            { "model": "gpt-4-1106-preview", "api_key": environ['OPENAI_API_KEY'] }
        ],
    } 

    user_proxy = autogen.UserProxyAgent(
        name="user_proxy",
        is_termination_msg=lambda x: x.get("content", "") and "TERMINATE" in x.get("content", "").rstrip()[-len("TERMINATE")-5:],
        human_input_mode="NEVER",
        max_consecutive_auto_reply=10,
        code_execution_config= {
            "work_dir": "code",
            "use_docker": False
        }
    )

    # Portainer Agent Setup #
    portainer_connection = {
        "url": environ['PORTAINER_URL'],
        "token": environ['PORTAINER_AUTH_TOKEN']
    }

    portainer_manager = PortainerAgent(name="Portainer Agent", description="Portainer RAG Agent", user_proxy=user_proxy, connection=portainer_connection, llm_config=llm_config)
    # END Portainer Agent Setup #

    # start the conversation
    user_proxy.initiate_chat(
        portainer_manager,
        max_consecutive_auto_reply=10,
        message="Create and start a hello-world container (the one provided by docker for use in their tutorial)"
    )
