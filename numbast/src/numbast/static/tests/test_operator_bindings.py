# SPDX-FileCopyrightText: Copyright (c) 2024 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

import pytest
from functools import partial

from numba import cuda
from numba.types import Type
from numba.core.datamodel import StructModel
from numba.cuda import device_array

from ast_canopy import parse_declarations_from_source

from numbast.static.renderer import get_rendered_imports, get_rendered_shims, get_prefix
from numbast.static.renderer import clear_base_renderer_cache
from numbast.static.struct import StaticStructsRenderer
from numbast.static.function import StaticFunctionsRenderer


@pytest.fixture(scope="module")
def cuda_decls(data_folder):
    clear_base_renderer_cache()

    header = data_folder("operator.cuh")

    specs = {"Foo": (Type, StructModel, header)}

    decls = parse_declarations_from_source(header, [header], "sm_50")
    structs = decls.structs
    functions = decls.functions

    assert len(structs) == 1

    SSR = StaticStructsRenderer(structs, specs)
    SFR = StaticFunctionsRenderer(functions, header)

    struct_bindings = SSR.render_as_str(
        with_prefix=False, with_imports=False, with_shim_functions=False
    )
    function_bindings = SFR.render_as_str(
        with_prefix=False, with_imports=False, with_shim_functions=False
    )

    bindings = "\n".join(
        [
            get_prefix(),
            get_rendered_imports(),
            struct_bindings,
            function_bindings,
            get_rendered_shims(),
        ]
    )

    globals = {}
    exec(bindings, globals)

    public_apis = [*specs, "c_ext_shim_source"]
    assert all(public_api in globals for public_api in public_apis)

    return {k: globals[k] for k in public_apis}


@pytest.fixture(scope="module")
def numbast_jit(cuda_decls):
    c_ext_shim_source = cuda_decls["c_ext_shim_source"]
    return partial(cuda.jit, link=[c_ext_shim_source])


def test_custom_type_operators(cuda_decls, numbast_jit):
    Foo = cuda_decls["Foo"]

    @numbast_jit
    def kernel(arr):
        foo = Foo(43)  # noqa: F841
        foo2 = Foo(42)
        foo3 = foo + foo2

        arr[0] = foo3.x

    arr = device_array((1,), "int32")
    kernel[1, 1](arr)
    assert all(arr.copy_to_host() == [85])
