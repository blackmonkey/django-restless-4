from django.core.exceptions import ImproperlyConfigured
from django.core.paginator import Paginator


class PaginatorMixin:
    """
    A simple pagination mixin that can be called simply by self.page(request.page)
    """
    model = ""
    paginate_by = 25

    def _check_for_model(self):
        if not self.model:
            raise ImproperlyConfigured("You must specify a model to use the paginator")
        return True

    def _check_for_pages(self):
        """
        Check for the existence of pages and initialize the Paginator if necessary.

        This function checks if `self.pages` is already set. If not, it initializes the Paginator
        using the specified `model` and `paginate_by` attributes. It returns True if the pages
        exist or have been successfully initialized.

        :return: True if the pages exist or have been successfully initialized.
        :raises ImproperlyConfigured: If `self.model` is not specified.
        :raises Exception: If an error occurs during the initialization of the Paginator.
        """
        if not self.pages:
            self._check_for_model()
            self.pages = Paginator(self.model.objects.all(), self.paginate_by)
            return True

    def page(self, page_num):
        if self._check_for_pages():
            if not isinstance(page_num, int):
                raise ValueError(
                    f"You must specify an integer value for your page number. {page_num} is not a valid number."
                )

            if page_num < 1:
                page_num = 1
            if page_num > self.pages.num_pages:
                page_num = self.pages.num_pages

            return self.pages.page(page_num).object_list
