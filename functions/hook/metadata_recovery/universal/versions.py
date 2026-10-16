#!/usr/bin/env python3

from __future__ import annotations

V39_NAMES = [
    "stringLiteral", "stringLiteralData", "string", "events", "properties",
    "methods", "parameterDefaultValues", "fieldDefaultValues",
    "fieldAndParameterDefaultValueData", "fieldMarshaledSizes", "parameters",
    "fields", "genericParameters", "genericParameterConstraints",
    "genericContainers", "nestedTypes", "interfaces", "vtableMethods",
    "interfaceOffsets", "typeDefinitions", "images", "assemblies", "fieldRefs",
    "referencedAssemblies", "attributeData", "attributeDataRange",
    "unresolvedVirtualCallParameterTypes",
    "unresolvedVirtualCallParameterRanges", "windowsRuntimeTypeNames",
    "windowsRuntimeStrings", "exportedTypeDefinitions",
]

V39_REC = {
    "stringLiteral": 4,
    "stringLiteralData": None,
    "string": None,
    "events": 24,
    "properties": 20,
    "methods": 32,
    "parameterDefaultValues": 12,
    "fieldDefaultValues": 12,
    "fieldAndParameterDefaultValueData": 1,
    "fieldMarshaledSizes": 12,
    "parameters": 12,
    "fields": 12,
    "genericParameters": 14,
    "genericParameterConstraints": 4,
    "genericContainers": 16,
    "nestedTypes": 4,
    "interfaces": 4,
    "vtableMethods": 4,
    "interfaceOffsets": 8,
    "typeDefinitions": 82,
    "images": 36,
    "assemblies": 68,
    "fieldRefs": 8,
    "referencedAssemblies": 4,
    "attributeData": None,
    "attributeDataRange": 8,
    "unresolvedVirtualCallParameterTypes": 4,
    "unresolvedVirtualCallParameterRanges": 8,
    "windowsRuntimeTypeNames": 0,
    "windowsRuntimeStrings": 0,
    "exportedTypeDefinitions": 4,
}

VERSIONS = {
    39: {
        "names": V39_NAMES,
        "rec": V39_REC,
    },
}

def version_table(metadata_version: int) -> dict:
    if metadata_version not in VERSIONS:
        raise ValueError(f"unsupported IL2CPP metadata version {metadata_version}")
    return VERSIONS[metadata_version]
