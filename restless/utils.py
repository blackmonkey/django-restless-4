from django.core.paginator import Paginator

class PaginatorMixin(object):
    """
    A simple pagination mixin that can be called simply by 
    self.page(request.page)
    """
    model = ""
    paginate_by = 25
    
    def _check_for_model(self):
        if model == "":
            raise Exception("You must specify a model to use the paginator")
        return True

    def _check_for_pages(self):
        if self.pages:
            return True
        else:
            self._check_for_model()
            try:
                self.pages = Paginator(
                    self.model.objects.all, 
                    self.paginate_by
                )
                return True
            except Exception as e:
                raise Exception()
            
    def page(self, page_num):
        if _check_for_pages:
            try:
                page_num = int(page_num)
            except as e:
                raise ValueError("""\
                You must specify an integer value for your page number. %s is \ 
                not a valid number. For more information, look at the \
                traceback. \
                %s
                """ % (page_num, e))
            if page_num < 1:
                page_num = 1
            if page_num > self.pages.num_pages:
                page_num = self.pages.num_page
            return pages.page(page_num).object_list
