"""Explicit trusted registrations; manifests never execute code or grant permissions."""
import re
from typing import Callable
from pydantic import BaseModel, Field, field_validator

class Port(BaseModel):
    id: str
    label: str
    type: str
    multiple: bool = False
    required: bool = True

class CapabilityManifest(BaseModel):
    schemaVersion: str = '1.0'
    id: str
    version: str
    name: str
    description: str
    execution: str
    inputs: list[Port]
    outputs: list[Port]
    parameters: dict = Field(default_factory=lambda: {'type':'object','properties':{}})
    permissions: list[str] = Field(default_factory=list)

    @field_validator('id')
    @classmethod
    def valid_id(cls,value):
        if not re.fullmatch(r'[a-z][a-z0-9-]*\.[a-z][a-z0-9.-]*',value): raise ValueError('Use a namespaced ID such as example.vectorize')
        return value

    @field_validator('schemaVersion')
    @classmethod
    def supported_version(cls,value):
        if value != '1.0': raise ValueError('Unsupported contract version')
        return value

    @field_validator('execution')
    @classmethod
    def valid_execution(cls,value):
        if value not in {'local','provider'}: raise ValueError('execution must be local or provider')
        return value

class NodeManifest(BaseModel):
    schemaVersion: str = '1.0'
    id: str
    name: str
    capability: str
    inputBindings: dict[str,str]
    outputBindings: dict[str,str]

class CapabilityRegistry:
    def __init__(self):
        self.capabilities = {}
        self.nodes = {}

    def register(self, manifest: dict, handler: Callable):
        spec = CapabilityManifest.model_validate(manifest)
        if spec.id in self.capabilities: raise ValueError('Duplicate capability ID')
        if not callable(handler): raise ValueError('Handler must be explicitly registered by the host')
        for ports in (spec.inputs,spec.outputs):
            if len({p.id for p in ports}) != len(ports): raise ValueError('Duplicate port ID')
        self.capabilities[spec.id] = (spec,handler)
        return spec

    def register_node(self, manifest: dict):
        node=NodeManifest.model_validate(manifest)
        if node.schemaVersion!='1.0' or node.id in self.nodes: raise ValueError('Invalid or duplicate node registration')
        if node.capability not in self.capabilities: raise ValueError('Missing capability')
        spec,_=self.capabilities[node.capability]
        for bindings,ports in ((node.inputBindings,spec.inputs),(node.outputBindings,spec.outputs)):
            if not set(bindings.values()) <= {p.id for p in ports}: raise ValueError('Unknown capability port')
        self.nodes[node.id]=node
        return node

    def execute(self, capability_id: str, context: dict, inputs: dict, parameters: dict):
        spec,handler=self.capabilities[capability_id]
        if any(p.required and p.id not in inputs for p in spec.inputs): raise ValueError('Missing required input')
        # The host supplies scoped asset access, cancellation and receipt handling.
        return handler(context=context,inputs=inputs,parameters=parameters)
