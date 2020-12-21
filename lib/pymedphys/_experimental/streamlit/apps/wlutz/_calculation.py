# Copyright (C) 2020 Cancer Care Associates

# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at

#     http://www.apache.org/licenses/LICENSE-2.0

# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
import base64

from pymedphys._imports import numpy as np
from pymedphys._imports import pandas as pd
from pymedphys._imports import plt, pylinac
from pymedphys._imports import streamlit as st

from pymedphys import _losslessjpeg as lljpeg
from pymedphys._wlutz import findbb, findfield, imginterp, iview
from pymedphys._wlutz import pylinac as pmp_pylinac_api
from pymedphys._wlutz import reporting

from . import _altair

RESULTS_DATA_COLUMNS = [
    "filepath",
    "algorithm",
    "diff_x",
    "diff_y",
    "field_centre_x",
    "field_centre_y",
    "field_rotation",
    "bb_centre_x",
    "bb_centre_y",
]


def run_calculation(
    database_table,
    database_directory,
    wlutz_directory_by_date,
    selected_algorithms,
    bb_diameter,
    penumbra,
):
    raw_results_csv_path = wlutz_directory_by_date.joinpath("raw_results.csv")
    try:
        previously_calculated_results = pd.read_csv(
            raw_results_csv_path, index_col=False
        )
    except FileNotFoundError:
        previously_calculated_results = None

    st.sidebar.write("---\n## Progress")
    progress_bar = st.sidebar.progress(0)
    status_text = st.sidebar.empty()

    collated_results = pd.DataFrame()
    chart_bucket = {}

    total_files = len(database_table["filepath"])

    for i, relative_image_path in enumerate(database_table["filepath"][::-1]):
        if previously_calculated_results is not None:
            results = previously_calculated_results.loc[
                previously_calculated_results["filepath"] == relative_image_path
            ][RESULTS_DATA_COLUMNS]

            selected_algorithms_already_calculated = set(selected_algorithms).issubset(
                results["algorithm"].unique()
            )

        if (
            previously_calculated_results is None
            or not selected_algorithms_already_calculated
        ):
            row = database_table.iloc[i]
            edge_lengths = [row["width"], row["length"]]
            # field_rotation = 90 - row["collimator"]

            results = get_results_for_image(
                database_directory,
                relative_image_path,
                selected_algorithms,
                bb_diameter,
                edge_lengths,
                penumbra,
            )

        collated_results = collated_results.append(results)

        working_table = results.merge(
            database_table, left_on="filepath", right_on="filepath"
        )

        working_table["transformed_field_rotation"] = (
            90 - working_table["field_rotation"] % 90
        )
        working_table["transformed_collimator"] = working_table["collimator"] % 90

        treatment = _collapse_column_to_single_value(working_table, "treatment")
        port = _collapse_column_to_single_value(working_table, "port")

        try:
            treatment_chart_bucket = chart_bucket[treatment]
        except KeyError:
            chart_bucket[treatment] = {}
            treatment_chart_bucket = chart_bucket[treatment]

        table_filtered_by_treatment = working_table.loc[
            working_table["treatment"] == treatment
        ]

        table_filtered_by_port = table_filtered_by_treatment.loc[
            table_filtered_by_treatment["port"] == port
        ]
        try:
            for _, item in treatment_chart_bucket[port].items():
                item.add_rows(table_filtered_by_port)
        except KeyError:
            st.write(f"### Treatment: `{treatment}` | Port: `{port}`")
            port_chart_bucket = _altair.build_both_axis_altair_charts(
                table_filtered_by_port
            )
            treatment_chart_bucket[port] = port_chart_bucket

        ratio_complete = (i + 1) / total_files
        progress_bar.progress(ratio_complete)

        percent_complete = round(ratio_complete * 100, 2)
        status_text.text(f"{percent_complete}% Complete")

    contextualised_results: pd.DataFrame = collated_results.merge(
        database_table, left_on="filepath", right_on="filepath"
    )

    st.write("## Raw results")
    st.write(contextualised_results)

    wlutz_directory_by_date.mkdir(parents=True, exist_ok=True)

    merged_with_previous = pd.concat(
        [contextualised_results, previously_calculated_results]
    )
    merged_with_previous.drop_duplicates(inplace=True)
    merged_with_previous.to_csv(raw_results_csv_path, index=False)

    statistics_collection = []

    for treatment, treatment_chart_bucket in chart_bucket.items():
        for port, port_chart_bucket in treatment_chart_bucket.items():
            for column, orientation in zip(
                ["diff_x", "diff_y"], ["Transverse", "Radial"]
            ):
                plot_filename = f"{treatment}-{port}-{orientation}.png"
                plot_filepath = wlutz_directory_by_date.joinpath(plot_filename)

                mask = (contextualised_results["treatment"] == treatment) & (
                    contextualised_results["port"] == port
                )

                masked = contextualised_results.loc[mask]

                fig, ax = plt.subplots()
                for algorithm in sorted(selected_algorithms):
                    algorithm_masked = masked.loc[masked["algorithm"] == algorithm]
                    ax.plot(
                        algorithm_masked["gantry"],
                        algorithm_masked[column],
                        ".-",
                        label=algorithm,
                    )

                    description = algorithm_masked[column].describe()
                    description = description.round(2)
                    description["algorithm"] = algorithm
                    description["treatment"] = treatment
                    description["port"] = port
                    description["orientation"] = orientation

                    statistics_collection.append(description)

                ax.set_xlabel("Gantry Angle (degrees)")
                ax.set_ylabel("Field centre - BB centre (mm)")

                descriptor = f"{treatment} | {port} | {orientation}"
                ax.set_title(descriptor)
                ax.grid("true")

                ax.legend(loc="best")
                fig.savefig(plot_filepath)

    st.write("## Overview Statistics")

    statistics_collection = pd.concat(statistics_collection, axis=1).T
    statistics_collection.reset_index(inplace=True)
    statistics_collection = statistics_collection[
        ["treatment", "port", "orientation", "algorithm", "min", "max", "mean"]
    ]

    st.write(statistics_collection)

    statistics_filename = "statistics_overview.csv"

    statistics_overview_csv_path = wlutz_directory_by_date.joinpath(statistics_filename)
    statistics_collection.to_csv(statistics_overview_csv_path, index=False)

    with open(statistics_overview_csv_path, "rb") as f:
        csv_bytes = f.read()

    b64 = base64.b64encode(csv_bytes).decode()
    href = f"""
        <a href=\"data:file/zip;base64,{b64}\" download='{statistics_filename}'>
            Download `{statistics_filename}`.
        </a>
    """
    st.markdown(href, unsafe_allow_html=True)


def _collapse_column_to_single_value(dataframe, column):
    results = dataframe[column].unique()
    if len(results) != 1:
        raise ValueError(f"Expected exactly one {column} per image")

    return results[0]


def get_results_for_image(
    database_directory,
    relative_image_path,
    selected_algorithms,
    bb_diameter,
    edge_lengths,
    penumbra,
):
    full_image_path = _get_full_image_path(database_directory, relative_image_path)

    results_data = []

    for algorithm in selected_algorithms:

        field_centre, field_rotation_calculated, bb_centre = _calculate_wlutz(
            full_image_path, algorithm, bb_diameter, edge_lengths, penumbra
        )
        results_data.append(
            {
                "filepath": relative_image_path,
                "algorithm": algorithm,
                "diff_x": field_centre[0] - bb_centre[0],
                "diff_y": field_centre[1] - bb_centre[1],
                "field_centre_x": field_centre[0],
                "field_centre_y": field_centre[1],
                "field_rotation": field_rotation_calculated,
                "bb_centre_x": bb_centre[0],
                "bb_centre_y": bb_centre[1],
            }
        )

    results = pd.DataFrame.from_dict(results_data)

    if set(results.columns) != set(RESULTS_DATA_COLUMNS):
        raise ValueError("Unexpected columns")

    return results


def plot_diagnostic_figures(
    database_directory,
    relative_image_path,
    bb_diameter,
    edge_lengths,
    penumbra,
    selected_algorithms,
):
    full_image_path = _get_full_image_path(database_directory, relative_image_path)
    wlutz_input_parameters = _get_wlutz_input_parameters(
        full_image_path, bb_diameter, edge_lengths, penumbra
    )

    figures = []

    for algorithm in selected_algorithms:
        field_centre, _, bb_centre = _calculate_wlutz(
            full_image_path, algorithm, bb_diameter, edge_lengths, penumbra
        )

        fig, axs = _create_figure(field_centre, bb_centre, wlutz_input_parameters)
        axs[0, 0].set_title(algorithm)
        figures.append(fig)

    return figures


def _create_figure(field_centre, bb_centre, wlutz_input_parameters):
    fig, axs = reporting.image_analysis_figure(
        wlutz_input_parameters["x"],
        wlutz_input_parameters["y"],
        wlutz_input_parameters["image"],
        bb_centre,
        field_centre,
        wlutz_input_parameters["field_rotation"],
        wlutz_input_parameters["bb_diameter"],
        wlutz_input_parameters["edge_lengths"],
        wlutz_input_parameters["penumbra"],
    )

    return fig, axs


def _get_full_image_path(database_directory, relative_image_path):
    return database_directory.joinpath(relative_image_path)


def _get_wlutz_input_parameters(image_path, bb_diameter, edge_lengths, penumbra):
    field_parameters = _get_field_parameters(image_path, edge_lengths, penumbra)
    wlutz_input_parameters = {
        "bb_diameter": bb_diameter,
        "edge_lengths": edge_lengths,
        "penumbra": penumbra,
        **field_parameters,
    }

    return wlutz_input_parameters


@st.cache(show_spinner=False)
def _calculate_wlutz(image_path, algorithm, bb_diameter, edge_lengths, penumbra):
    wlutz_input_parameters = _get_wlutz_input_parameters(
        image_path, bb_diameter, edge_lengths, penumbra
    )

    if wlutz_input_parameters["field_rotation"] == np.nan:
        field_centre = [np.nan, np.nan]
        field_rotation = np.nan
        bb_centre = [np.nan, np.nan]
    else:
        calculate_function = ALGORITHM_FUNCTION_MAP[algorithm]
        field_centre, field_rotation, bb_centre = calculate_function(
            **wlutz_input_parameters
        )

    return field_centre, field_rotation, bb_centre


def _pymedphys_wlutz_calculate(
    field,
    bb_diameter,
    edge_lengths,
    penumbra,
    pymedphys_field_centre,
    field_rotation,
    **_,
):
    field_centre = pymedphys_field_centre

    try:
        bb_centre = findbb.optimise_bb_centre(
            field,
            bb_diameter,
            edge_lengths,
            penumbra,
            field_centre,
            field_rotation,
            pylinac_tol=None,
        )
    except ValueError:
        bb_centre = [np.nan, np.nan]

    return field_centre, field_rotation, bb_centre


def _pylinac_wlutz_calculate(
    field, edge_lengths, penumbra, pymedphys_field_centre, field_rotation, **_
):
    version_to_use = pylinac.__version__

    try:
        pylinac_results = pmp_pylinac_api.run_wlutz(
            field,
            edge_lengths,
            penumbra,
            pymedphys_field_centre,
            field_rotation,
            find_bb=True,
            interpolated_pixel_size=0.05,
            pylinac_versions=[version_to_use],
            fill_errors_with_nan=True,
        )

        field_centre = pylinac_results[version_to_use]["field_centre"]
        bb_centre = pylinac_results[version_to_use]["bb_centre"]

    except ValueError:
        field_centre = [np.nan, np.nan]
        bb_centre = [np.nan, np.nan]

    return field_centre, field_rotation, bb_centre


ALGORITHM_FUNCTION_MAP = {
    "PyMedPhys": _pymedphys_wlutz_calculate,
    "PyLinac": _pylinac_wlutz_calculate,
}


@st.cache(show_spinner=False)
def _get_pymedphys_field_centre_and_rotation(image_path, edge_lengths, penumbra):
    x, y, image, field = _load_image_field_interpolator(image_path)
    initial_centre = findfield.get_centre_of_mass(x, y, image)

    try:
        field_centre, field_rotation = findfield.field_centre_and_rotation_refining(
            field, edge_lengths, penumbra, initial_centre, pylinac_tol=None
        )
    except ValueError:
        field_centre = [np.nan, np.nan]
        field_rotation = np.nan

    return field_centre, field_rotation


def _load_image_field_interpolator(image_path):
    raw_image = lljpeg.imread(image_path)
    x, y, image = iview.iview_image_transform(raw_image)
    field = imginterp.create_interpolated_field(x, y, image)

    return x, y, image, field


def _get_field_parameters(image_path, edge_lengths, penumbra):
    x, y, image, field = _load_image_field_interpolator(image_path)
    field_centre, field_rotation = _get_pymedphys_field_centre_and_rotation(
        image_path, edge_lengths, penumbra
    )

    return {
        "x": x,
        "y": y,
        "image": image,
        "field": field,
        "pymedphys_field_centre": field_centre,
        "field_rotation": field_rotation,
    }
