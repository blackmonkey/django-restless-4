from django.db import models

__all__ = ['Author', 'Book', 'Publisher']


class Publisher(models.Model):
    name = models.CharField(max_length=255)


class Author(models.Model):
    name = models.CharField(max_length=255)


class Book(models.Model):
    author = models.ForeignKey(Author, related_name='books', on_delete=models.CASCADE)
    publisher = models.ForeignKey(Publisher, related_name='publisher', on_delete=models.CASCADE)
    title = models.CharField(max_length=255)
    isbn = models.CharField(max_length=64, unique=True)
    price = models.DecimalField(max_digits=20, decimal_places=2)
