from django.urls import reverse
from rest_framework import status
from the_music_tree_api_kit.view.error.ErrorResponseFields import ErrorResponseFields
from the_music_tree_api_kit.view.pagination.PaginatedResponseFields import PaginatedResponseFields

from grow.model.criteria.children.genre.Genre import Genre
from tests.utils.AppTestCase import AppTestCase


class GenreTestCase(AppTestCase):
    model_class = Genre
    list_endpoint = "genre-list"

    def _list_genres(self, **kwargs):
        return self.api_client.get(path=reverse(self.list_endpoint), data=kwargs, handle_response=self._set_results)

    def _get_genres_tree(self):
        return self.api_client.get(
            path=reverse(self.list_endpoint) + "tree/", handle_response=self._set_error_response_result_if_failure
        )

    def _post_genres_tree_import(self, data=None):
        return self.api_client.post(
            path=reverse(self.list_endpoint) + "tree/import/",
            data=data,
            handle_response=self._set_results,
        )

    def _post_genres_tree_load_example(self):
        return self.api_client.post(
            path=reverse(self.list_endpoint) + "tree/load-example/",
            handle_response=self._set_results,
        )

    def _delete_genre(self, uuid):
        return self.api_client.delete(path=reverse("genre-detail", kwargs={"pk": uuid}))

    def _set_results(self, response):
        if response.status_code in [status.HTTP_200_OK, status.HTTP_201_CREATED]:
            response_json = response.json()
            if isinstance(response_json, dict) and PaginatedResponseFields.RESULTS in response_json:
                self.results = response_json[PaginatedResponseFields.RESULTS]
                self.results_overall_total = response_json[PaginatedResponseFields.OVERALL_TOTAL]
        else:
            self._set_error_response_result_if_failure(response)

    def _set_error_response_result_if_failure(self, response):
        if response.status_code in [status.HTTP_200_OK, status.HTTP_201_CREATED]:
            return

        self.bad_request_result = response.json()
        bad_request_result_details = self.bad_request_result.get(ErrorResponseFields.DETAILS, {})
        bad_request_result_field_errors_json = (
            bad_request_result_details.get(ErrorResponseFields.FIELD_ERRORS)
            if isinstance(bad_request_result_details, dict)
            else None
        )
        self.bad_request_result_field_errors = []
        if bad_request_result_field_errors_json:
            for field_name, error_list in bad_request_result_field_errors_json.items():
                for error in error_list:
                    self.bad_request_result_field_errors.append(
                        {"field": field_name, "message": error["message"], "code": error["code"]}
                    )
