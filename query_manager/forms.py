from django import forms
from .models import DatabaseConnection


class DatabaseConnectionForm(forms.ModelForm):
    """데이터베이스 연결 폼"""
    password = forms.CharField(
        widget=forms.PasswordInput(attrs={'class': 'form-control'}),
        required=True,
        label='비밀번호'
    )

    class Meta:
        model = DatabaseConnection
        fields = ['name', 'host', 'port', 'database', 'username', 'password', 'schema', 'hosts', 'is_active']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': '연결 이름'}),
            'host': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'localhost'}),
            'port': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': '3306'}),
            'database': forms.TextInput(attrs={'class': 'form-control', 'placeholder': '데이터베이스명 (선택)'}),
            'username': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'root'}),
            'schema': forms.TextInput(attrs={'class': 'form-control', 'placeholder': '스키마 (선택)'}),
            'hosts': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 4,
                'placeholder': 'db-server-01.example.com\ndb-server-02.example.com\ndb-server-03.example.com'
            }),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }
        help_texts = {
            'database': '비워두면 서버 레벨 연결로 사용됩니다.',
            'schema': 'MariaDB의 경우 보통 비워둡니다.',
            'hosts': '다중 서버 지원: 여러 호스트를 줄바꿈으로 구분하여 입력. 비워두면 위의 호스트만 사용됩니다.',
        }


class DatabaseConnectionEditForm(DatabaseConnectionForm):
    """데이터베이스 연결 수정 폼 (비밀번호 선택적)"""
    password = forms.CharField(
        widget=forms.PasswordInput(attrs={'class': 'form-control', 'placeholder': '변경하지 않으려면 비워두세요'}),
        required=False,
        label='비밀번호'
    )

    def clean_password(self):
        password = self.cleaned_data.get('password')
        if not password and self.instance and self.instance.pk:
            return self.instance.password
        return password


class QueryExecuteForm(forms.Form):
    """쿼리 실행 폼"""
    connection = forms.ModelChoiceField(
        queryset=DatabaseConnection.objects.filter(is_active=True),
        widget=forms.Select(attrs={'class': 'form-select'}),
        label='DB 연결',
        empty_label='연결을 선택하세요...'
    )
    database = forms.CharField(
        required=False,
        widget=forms.Select(attrs={'class': 'form-select'}),
        label='데이터베이스'
    )
    query = forms.CharField(
        widget=forms.Textarea(attrs={
            'class': 'form-control',
            'rows': 10,
            'placeholder': 'SQL 쿼리를 입력하세요...',
            'id': 'sql-editor'
        }),
        label='SQL 쿼리'
    )


class HistoryFilterForm(forms.Form):
    """히스토리 필터 폼"""
    QUERY_TYPE_CHOICES = [
        ('', '모든 유형'),
        ('SELECT', 'SELECT'),
        ('INSERT', 'INSERT'),
        ('UPDATE', 'UPDATE'),
        ('DELETE', 'DELETE'),
        ('DDL', 'DDL'),
        ('OTHER', '기타'),
    ]

    STATUS_CHOICES = [
        ('', '모든 상태'),
        ('SUCCESS', '성공'),
        ('FAILED', '실패'),
    ]

    CATEGORY_CHOICES = [
        ('', '모든 카테고리'),
        ('DDL', 'DDL (CREATE, ALTER, DROP)'),
        ('DML', 'DML (INSERT, UPDATE, DELETE)'),
        ('DQL', 'DQL (SELECT)'),
    ]

    connection = forms.ModelChoiceField(
        queryset=DatabaseConnection.objects.all(),
        required=False,
        widget=forms.Select(attrs={'class': 'form-select'}),
        label='DB 연결',
        empty_label='모든 연결'
    )
    category = forms.ChoiceField(
        choices=CATEGORY_CHOICES,
        required=False,
        widget=forms.Select(attrs={'class': 'form-select'}),
        label='카테고리'
    )
    query_type = forms.ChoiceField(
        choices=QUERY_TYPE_CHOICES,
        required=False,
        widget=forms.Select(attrs={'class': 'form-select'}),
        label='쿼리 유형'
    )
    status = forms.ChoiceField(
        choices=STATUS_CHOICES,
        required=False,
        widget=forms.Select(attrs={'class': 'form-select'}),
        label='상태'
    )
    operator = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': '작업자명...'}),
        label='작업자'
    )
    search = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': '쿼리 내용 검색...'}),
        label='검색'
    )
    date_from = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
        label='시작일',
        input_formats=['%Y-%m-%d', '%Y/%m/%d', '%d-%m-%Y', '%d/%m/%Y']
    )
    date_to = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
        label='종료일',
        input_formats=['%Y-%m-%d', '%Y/%m/%d', '%d-%m-%Y', '%d/%m/%Y']
    )


class VersionTagForm(forms.Form):
    """버전 태그 폼"""
    tag_name = forms.CharField(
        max_length=100,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': '태그명'}),
        label='태그명'
    )
    memo = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'placeholder': '메모'}),
        label='메모'
    )
